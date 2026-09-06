import hashlib

def sha256_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

from web3 import Web3

def make_commitment(face_hash: str, url: str, timestamp: int) -> bytes:
    return Web3.solidity_keccak(['string', 'string', 'uint256'], [face_hash, url, timestamp])

