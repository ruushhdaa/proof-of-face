"""Blockchain integration module for Proof of Face.

Supports two modes via config NETWORK:
1. 'local': Uses web3.EthereumTesterProvider() so contract deployment,
   transaction commit, and view verification run instantly in-memory without
   testnet faucets or gas fees.
2. 'amoy': Connects to Polygon Amoy Testnet via web3.py HTTPProvider and private key.

Methods:
- deploy_contract(): Compiles/deploys the Solidity contract if no CONTRACT_ADDRESS is provided.
- create_commitment(face_hash, post_url, timestamp): Returns web3.solidity_keccak(['string', 'string', 'uint256'], [face_hash, post_url, timestamp]).
- record_match_on_chain(commitment, post_url, confidence): Submits transaction and returns tx_hash.
- verify_match_on_chain(commitment): Queries verifyAttestation and returns on-chain record data.
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

from eth_account import Account
from hexbytes import HexBytes
from web3 import Web3

# Add project root to sys.path
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

try:
    from src.config import CONTRACT_ADDRESS, NETWORK, PRIVATE_KEY, WEB3_PROVIDER_URI
except ImportError:
    CONTRACT_ADDRESS = ""
    NETWORK = "local"
    PRIVATE_KEY = ""
    WEB3_PROVIDER_URI = "https://rpc-amoy.polygon.technology/"

try:
    from src.bytecode import FACE_ATTESTATION_BYTECODE
except ImportError:
    FACE_ATTESTATION_BYTECODE = ""

# FaceAttestation ABI
FACE_ATTESTATION_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "bytes32", "name": "commitmentHash", "type": "bytes32"},
            {"indexed": True, "internalType": "address", "name": "attestor", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "timestamp", "type": "uint256"},
        ],
        "name": "AttestationRecorded",
        "type": "event",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "", "type": "bytes32"}],
        "name": "attestations",
        "outputs": [
            {"internalType": "bytes32", "name": "commitmentHash", "type": "bytes32"},
            {"internalType": "string", "name": "postUrl", "type": "string"},
            {"internalType": "uint256", "name": "confidence", "type": "uint256"},
            {"internalType": "uint256", "name": "timestamp", "type": "uint256"},
            {"internalType": "address", "name": "attestor", "type": "address"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "bytes32", "name": "commitmentHash", "type": "bytes32"},
            {"internalType": "string", "name": "postUrl", "type": "string"},
            {"internalType": "uint256", "name": "confidence", "type": "uint256"},
        ],
        "name": "recordAttestation",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "commitmentHash", "type": "bytes32"}],
        "name": "verifyAttestation",
        "outputs": [
            {"internalType": "bool", "name": "exists", "type": "bool"},
            {"internalType": "string", "name": "postUrl", "type": "string"},
            {"internalType": "uint256", "name": "confidence", "type": "uint256"},
            {"internalType": "uint256", "name": "timestamp", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "commitmentHash", "type": "bytes32"}],
        "name": "verifyMatch",
        "outputs": [
            {"internalType": "bool", "name": "exists", "type": "bool"},
            {"internalType": "string", "name": "postUrl", "type": "string"},
            {"internalType": "uint256", "name": "confidence", "type": "uint256"},
            {"internalType": "uint256", "name": "timestamp", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "commitmentHash", "type": "bytes32"}],
        "name": "getRecord",
        "outputs": [
            {"internalType": "bool", "name": "exists", "type": "bool"},
            {"internalType": "string", "name": "postUrl", "type": "string"},
            {"internalType": "uint256", "name": "confidence", "type": "uint256"},
            {"internalType": "uint256", "name": "timestamp", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
]


class BlockchainClient:
    """Web3 client managing testnet or local in-memory eth-tester connection."""

    def __init__(
        self,
        network: Optional[str] = None,
        provider_uri: Optional[str] = None,
        private_key: Optional[str] = None,
        contract_address: Optional[str] = None,
    ):
        self.network = (network or NETWORK).lower()
        self.provider_uri = provider_uri or WEB3_PROVIDER_URI
        self.private_key = private_key or PRIVATE_KEY
        self.contract_address = contract_address or CONTRACT_ADDRESS

        if self.network == "amoy":
            self.w3 = Web3(Web3.HTTPProvider(self.provider_uri))
            if self.private_key:
                self.account = Account.from_key(self.private_key)
                self.default_account = self.account.address
            else:
                self.account = None
                self.default_account = None
        else:
            # Local mode: in-memory simulated EVM chain via EthereumTesterProvider
            from web3.providers.eth_tester import EthereumTesterProvider

            self.w3 = Web3(EthereumTesterProvider())
            self.account = None
            self.default_account = (
                self.w3.eth.accounts[0] if self.w3.eth.accounts else None
            )

        # Path for local state persistence (search cwd and project_root)
        self.state_file = Path.cwd() / ".local_chain_state.json"
        if not self.state_file.exists() and (project_root / ".local_chain_state.json").exists():
            self.state_file = project_root / ".local_chain_state.json"

        # Automatically deploy or attach contract
        if not self.contract_address and self.network == "local":
            self.deploy_contract()
            self._restore_local_state()

    def _restore_local_state(self):
        """Restore saved local attestations into in-memory EVM contract."""
        if self.network != "local" or not self.state_file.exists():
            return
        try:
            with open(self.state_file, "r") as f:
                saved_state = json.load(f)
            contract = self.get_contract()
            for item in saved_state.get("attestations", []):
                comm_bytes = HexBytes(item["commitment"])
                exists, _, _, _ = contract.functions.verifyAttestation(comm_bytes).call()
                if not exists:
                    tx_hash = contract.functions.recordAttestation(
                        comm_bytes, item["post_url"], item["confidence"]
                    ).transact({"from": self.default_account})
                    self.w3.eth.wait_for_transaction_receipt(tx_hash)
        except Exception:
            pass

    def _save_local_attestation(self, commitment_hex: str, post_url: str, scaled_confidence: int, tx_hash: str):
        """Persist local attestation to state file for cross-process CLI consistency."""
        if self.network != "local":
            return
        state = {"attestations": []}
        if self.state_file.exists():
            try:
                with open(self.state_file, "r") as f:
                    state = json.load(f)
            except Exception:
                state = {"attestations": []}
        
        norm_hex = str(commitment_hex.hex() if hasattr(commitment_hex, "hex") else commitment_hex).replace("0x", "").lower()
        tx_str = str(tx_hash.hex() if hasattr(tx_hash, "hex") else tx_hash)
        existing = [
            item
            for item in state.get("attestations", [])
            if str(item.get("commitment", "")).replace("0x", "").lower() != norm_hex
        ]
        existing.append({
            "commitment": norm_hex,
            "post_url": str(post_url),
            "confidence": int(scaled_confidence),
            "tx_hash": tx_str,
            "timestamp": int(time.time()),
        })
        state["attestations"] = existing
        dumped = json.dumps(state, indent=2)
        with open(self.state_file, "w", encoding="utf-8") as f:
            f.write(dumped)

    def is_connected(self) -> bool:
        """Check if connection to provider is active."""
        return bool(self.w3.is_connected())

    def deploy_contract(self) -> str:
        """Compiles/deploys the Solidity contract if no CONTRACT_ADDRESS is provided."""
        contract_factory = self.w3.eth.contract(
            abi=FACE_ATTESTATION_ABI, bytecode=FACE_ATTESTATION_BYTECODE
        )

        if self.network == "amoy":
            if not self.account:
                raise ValueError("PRIVATE_KEY is required to deploy on Polygon Amoy.")

            sender = self.account.address
            nonce = self.w3.eth.get_transaction_count(sender)
            chain_id = self.w3.eth.chain_id

            tx = contract_factory.constructor().build_transaction(
                {
                    "from": sender,
                    "nonce": nonce,
                    "gas": 1500000,
                    "maxFeePerGas": self.w3.to_wei("35", "gwei"),
                    "maxPriorityFeePerGas": self.w3.to_wei("30", "gwei"),
                    "chainId": chain_id,
                }
            )
            signed_tx = self.w3.eth.account.sign_transaction(tx, self.private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            self.contract_address = str(receipt.contractAddress)
            return self.contract_address
        else:
            # Local in-memory deployment
            if not self.default_account:
                raise ValueError("No local accounts available to deploy contract.")
            tx_hash = contract_factory.constructor().transact(
                {"from": self.default_account}
            )
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
            self.contract_address = str(receipt.contractAddress)
            return self.contract_address

    def get_contract(self, address: Optional[str] = None):
        """Get contract instance bound to address."""
        target_addr = address or self.contract_address
        if not target_addr:
            target_addr = self.deploy_contract()
        checksum_address = self.w3.to_checksum_address(target_addr)
        return self.w3.eth.contract(address=checksum_address, abi=FACE_ATTESTATION_ABI)

    def create_commitment(
        self,
        face_hash: str,
        post_url: str,
        timestamp: int,
    ) -> HexBytes:
        """Returns web3.solidity_keccak(["string", "string", "uint256"], [face_hash, post_url, timestamp])."""
        commitment = Web3.solidity_keccak(
            ["string", "string", "uint256"],
            [str(face_hash), str(post_url), int(timestamp)],
        )
        return HexBytes(commitment)

    def record_match_on_chain(
        self,
        commitment: Union[bytes, str, HexBytes],
        post_url: str,
        confidence: float,
    ) -> str:
        """Submits the transaction to record attestation and returns tx_hash."""
        contract = self.get_contract()
        if isinstance(commitment, str):
            commitment_bytes = HexBytes(commitment.replace("0x", ""))
        else:
            commitment_bytes = HexBytes(commitment)

        # Scale float confidence (e.g. 0.9771 -> 9771)
        scaled_confidence = (
            int(confidence * 10000) if confidence <= 1.0 else int(confidence)
        )

        if self.network == "amoy":
            if not self.account:
                raise ValueError("PRIVATE_KEY is required for Polygon Amoy network.")

            sender = self.account.address
            nonce = self.w3.eth.get_transaction_count(sender)
            chain_id = self.w3.eth.chain_id

            tx = contract.functions.recordAttestation(
                commitment_bytes, str(post_url), scaled_confidence
            ).build_transaction(
                {
                    "from": sender,
                    "nonce": nonce,
                    "gas": 300000,
                    "maxFeePerGas": self.w3.to_wei("35", "gwei"),
                    "maxPriorityFeePerGas": self.w3.to_wei("30", "gwei"),
                    "chainId": chain_id,
                }
            )
            signed_tx = self.w3.eth.account.sign_transaction(tx, self.private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            return tx_hash.hex()
        else:
            # Local transaction
            tx_hash = contract.functions.recordAttestation(
                commitment_bytes, str(post_url), scaled_confidence
            ).transact({"from": self.default_account})
            self.w3.eth.wait_for_transaction_receipt(tx_hash)
            tx_hex = tx_hash.hex()
            self._save_local_attestation(
                commitment_bytes.hex(), str(post_url), scaled_confidence, tx_hex
            )
            return tx_hex

    def get_tx_details(self, tx_hash_hex: str) -> Dict[str, Any]:
        """Fetch transaction receipt details including block number and attestor address."""
        receipt = self.w3.eth.get_transaction_receipt(tx_hash_hex)
        sender = receipt.get("from") or self.default_account
        return {
            "tx_hash": tx_hash_hex,
            "block_number": receipt.blockNumber,
            "attestor": str(sender),
            "contract_address": self.contract_address,
        }

    def verify_match_on_chain(
        self,
        commitment: Union[bytes, str, HexBytes],
    ) -> Dict[str, Any]:
        """Queries verifyAttestation on-chain and returns record data."""
        contract = self.get_contract()
        if isinstance(commitment, str):
            commitment_bytes = HexBytes(commitment.replace("0x", ""))
        else:
            commitment_bytes = HexBytes(commitment)

        exists, post_url, raw_confidence, timestamp = (
            contract.functions.verifyAttestation(commitment_bytes).call()
        )

        if not exists and self.network == "local" and self.state_file.exists():
            try:
                target_hex = commitment_bytes.hex().replace("0x", "").lower()
                with open(self.state_file, "r") as f:
                    saved_state = json.load(f)
                for item in saved_state.get("attestations", []):
                    item_hex = str(item.get("commitment", "")).replace("0x", "").lower()
                    if item_hex == target_hex:
                        tx_hash = contract.functions.recordAttestation(
                            commitment_bytes, item["post_url"], item["confidence"]
                        ).transact({"from": self.default_account})
                        self.w3.eth.wait_for_transaction_receipt(tx_hash)
                        exists, post_url, raw_confidence, timestamp = (
                            contract.functions.verifyAttestation(commitment_bytes).call()
                        )
                        break
            except Exception:
                pass

        confidence = (
            round(raw_confidence / 10000.0, 4)
            if raw_confidence > 100
            else float(raw_confidence)
        )

        return {
            "exists": bool(exists),
            "commitment_hash": commitment_bytes.hex(),
            "post_url": post_url,
            "confidence": confidence,
            "raw_confidence": int(raw_confidence),
            "timestamp": int(timestamp),
            "contract_address": self.contract_address,
            "network": self.network,
        }
