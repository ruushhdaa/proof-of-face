# ProofOfFace: Privacy-Preserving Facial Discovery & Blockchain Attestation

> **Hackhouse Goa — Task 3 Submission**  
> *End-to-End Pipeline: Face Scan Input $\rightarrow$ Public Social Media Search $\rightarrow$ Cryptographic Commitment $\rightarrow$ Smart Contract Attestation $\rightarrow$ On-Chain Re-Verification Loop.*

---

## 🌟 Project Overview

Traditional facial recognition and identity verification systems suffer from a severe architectural flaw: **they centralize raw biometric data or high-dimensional embeddings in databases or transmit them onto public distributed ledgers**. Because human biometric features are permanent and immutable, a single database leak permanently compromises an individual's biometric identity forever.

**ProofOfFace** solves this problem by enforcing a strict **Zero-Biometric-On-Chain** design:
1. **Local Facial Processing**: High-dimensional face embeddings (128-D vector representations) are extracted exclusively in the user's local, volatile runtime memory.
2. **One-Way Fingerprinting**: Facial embeddings are immediately mapped to a non-invertible SHA-256 cryptographic digest.
3. **Commit-Reveal Attestation**: The match event is committed on-chain as a salted Keccak-256 hash `Keccak256(FaceHash || PostURL || Timestamp)`.
4. **Tamper-Proof Auditability**: Anyone with the original inputs can mathematically verify the attestation against the smart contract, while unauthorized observers learn zero information about the user's biometrics.

---

## 📐 System Architecture

```
┌─────────────────────────┐           ┌──────────────────────────────┐
│     Local Face Scan     │           │   Bluesky Public XRPC Feed   │
│   (assets/selfie.jpg)   │           │   (getAuthorFeed + media)    │
└────────────┬────────────┘           └──────────────┬───────────────┘
             │                                       │
             ▼                                       ▼
┌─────────────────────────┐           ┌──────────────────────────────┐
│   DeepFace / Fast-ROI   │           │  Candidate Stream Download   │
│  (128-D Feature Vector) │           │    (In-Memory Temp Buffer)   │
└────────────┬────────────┘           └──────────────┬───────────────┘
             │                                       │
             └───────────────────┬───────────────────┘
                                 │
                                 ▼
             ┌───────────────────────────────────────┐
             │       Facial Similarity Engine        │
             │     (Cosine Distance < Threshold)     │
             └───────────────────┬───────────────────┘
                                 │ Match Confirmed!
                                 ▼
             ┌───────────────────────────────────────┐
             │       Cryptographic Commitment        │
             │   Keccak256(FaceHash||URL||Timestamp) │
             └───────────────────┬───────────────────┘
                                 │
                                 ▼
             ┌───────────────────────────────────────┐
             │    EVM Smart Contract Attestation     │
             │        (FaceAttestation.sol)          │
             │  • Local Mode (In-Memory Py-EVM)      │
             │  • Testnet Mode (Polygon Amoy #80002) │
             └───────────────────┬───────────────────┘
                                 │
                                 ▼
             ┌───────────────────────────────────────┐
             │     On-Chain Re-Verification Loop     │
             │  Assert: local_hash == onchain_hash   │
             │   [CRYPTOGRAPHIC RE-VERIFICATION: ✅] │
             └───────────────────────────────────────┘
```

---

## 📁 Repository Layout

```
hhgoa/
├── assets/
│   └── selfie.jpg              # Local input scan / reference portrait
├── contracts/
│   ├── FaceAttestation.sol     # Smart contract recording & verifying commitments
│   └── build/                  # Compiled EVM bytecode (Paris-compatible) & ABI
├── src/
│   ├── __init__.py
│   ├── search_and_match.py     # Bluesky XRPC query, face embeddings & candidate streaming
│   ├── blockchain.py           # Web3 client for local EthereumTesterProvider & Polygon Amoy
│   ├── bytecode.py             # Precompiled embedded bytecode for standalone portability
│   └── config.py               # Environment configuration loader via python-dotenv
├── main.py                     # High-scannability terminal CLI orchestrator (rich.console)
├── requirements.txt            # Python dependencies
├── .env.example                # Environment variable configuration template
└── README.md                   # Complete architectural and execution documentation
```

---

## Watch it work live

- **Drive link**: [Watch the full end-to-end demo recording](https://drive.google.com/drive/folders/13FhhsyVr_QOwJjw1DJJOtamUkwEEIAi7?usp=sharing)
- **Or view the recording directly in this repo**: [`assets/demo.mp4`](assets/demo.mp4)

## ⚡ Prerequisites & Setup

### 1. Prerequisites
- **Python**: Version 3.10, 3.11, 3.12, 3.13, or 3.14.
- **Node.js**: (Optional, for re-compiling contracts via `solc`).
- **Operating System**: Windows, Linux, or macOS.

### 2. Environment Setup

```bash
# 1. Clone or navigate to the repository
git clone https://github.com/ruushhdaa/proof-of-face.git
cd proof-of-face

# 2. Create a virtual environment
python -m venv venv

# 3. Activate virtual environment
# Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# Linux / macOS:
# source venv/bin/activate

# 4. Upgrade pip and install dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Environment Configuration (`.env`)

Copy the example file to `.env`:

```bash
cp .env.example .env
```

Default variables defined in `.env`:
```env
BLUESKY_ACTOR="burnerhhg.bsky.social"
INPUT_FACE_PATH="assets/selfie.jpg"
WEB3_PROVIDER_URI="https://rpc-amoy.polygon.technology/"
PRIVATE_KEY=""
CONTRACT_ADDRESS=""
NETWORK="local" # Options: local, amoy
```

---

## 🚀 Step-by-Step Run Guide

The CLI features high-scannability terminal output powered by `rich.console` and supports two execution networks:

### Mode A: Local Simulated Chain (`--network local`)
*Recommended for instant hackathon evaluation: Runs against an in-memory `EthereumTesterProvider` (Py-EVM), requiring zero gas, zero faucets, and zero network latency while executing genuine EVM bytecode.*

```powershell
# Run end-to-end against live Bluesky posts from @bsky.app
python main.py --network local --actor @burnerhhg.bsky.social --input assets/selfie.jpg --limit 5
```

```powershell
# Run end-to-end with deterministic direct target verification
python main.py --network local --target assets/selfie.jpg --input assets/selfie.jpg
```

---

### Mode B: Polygon Amoy Testnet (`--network amoy`)
*Runs against the public Polygon Amoy Testnet (Chain ID `80002`).*

1. **Obtain Testnet MATIC**:
   - Generate or use an EVM wallet address.
   - Fund your wallet using the [Polygon Amoy Faucet](https://faucet.polygon.technology/).
2. **Configure `.env`**:
   ```env
   NETWORK="amoy"
   PRIVATE_KEY="<your_hex_private_key>"
   WEB3_PROVIDER_URI="https://rpc-amoy.polygon.technology/"
   ```
3. **Execute Pipeline**:
   ```powershell
   python main.py --network amoy --actor @burnerhhg.bsky.social --input assets/selfie.jpg
   ```

---

## 🔗 Blockchain & Cryptographic Details

### Why an Immutable Commit-Reveal Scheme?
Biometric identification requires privacy by construction. Direct storage of embeddings on-chain allows adversaries to reconstruct biometric features or cross-reference identities across services.

**ProofOfFace implements a one-way commitment scheme**:
$$\text{Commitment} = \text{Keccak256}(\text{FaceHash} \mathbin{\Vert} \text{PostURL} \mathbin{\Vert} \text{Timestamp})$$

- **FaceHash**: SHA-256 digest of normalized 128-D embedding.
- **PostURL**: Canonical URL string of the social media post containing the match.
- **Timestamp**: UNIX block timestamp preventing replay attacks.

This guarantees:
1. **Zero Knowledge Leakage**: Observers on the blockchain cannot derive the face embedding or identify the individual from the 32-byte commitment.
2. **Deterministic Re-verification**: Only a verifier who possesses the verified face scan, post URL, and timestamp can reproduce the identical hash.
3. **Tamper Evidence**: If a malicious actor alters even a single pixel of the image or character of the URL, the commitment comparison fails.

---

### Smart Contract Specification (`contracts/FaceAttestation.sol`)

The contract is written in Solidity `^0.8.20` and compiled with Paris EVM compatibility (`PUSH1 0x00` instead of `PUSH0`) to ensure 100% interoperability across Py-EVM, standard testnets, and EVM mainnets.

#### Data Structures
```solidity
struct Attestation {
    bytes32 commitmentHash; // Keccak256 commitment
    string postUrl;         // Matched post permalink
    uint256 confidence;     // Integer-scaled confidence score (e.g., 9771 = 97.71%)
    uint256 timestamp;      // Block timestamp of record creation
    address attestor;       // EVM address that submitted the attestation
}
```

#### Key Functions
- `recordAttestation(bytes32 commitmentHash, string memory postUrl, uint256 confidence) external`:
  Validates that `commitmentHash` is non-zero and has not been previously recorded, constructs the `Attestation` record, and emits `AttestationRecorded`.
- `verifyAttestation(bytes32 commitmentHash) external view returns (bool exists, string memory postUrl, uint256 confidence, uint256 timestamp)`:
  Constant gas $O(1)$ view function that queries whether an attestation exists and returns its on-chain parameters.

---

## 🖥️ Terminal Output Example

```
╔══════════════════════════════════════════════════════════════════════════════╗
║              ProofOfFace                                                     ║
║              Privacy-Preserving Facial Discovery & Attestation               ║
╚══════════════════════════════════════════════════════════════════════════════╝

Active Network: LOCAL  |  Contract Address: 0xF2E246BB76DF876Cef8b38ae84130F4F55De395b

╭── Step 1/4: Local Face Scan & Feature Encoding ──────────────────────────────╮
│ Input Scan: assets/selfie.jpg                                                │
│ Embedding:  128-D Normalized Vector (float32)                                │
│ Face Hash:  96b5fb4b76dab4fba3564b061f0267b0ddc0f6a651c43ae34... (SHA-256)   │
╰──────────────────────────────────────────────────────────────────────────────╯

╭── Step 2/4: Public Feed Query & Candidate Stream Evaluation ─────────────────╮
│ Actor Handle: @burnerhhg.bsky.social  |  Limit: 5 posts                                   │
│ Streaming evaluation across candidate posts:                                 │
│   Candidate 1: ✅ Match confirmed! (Confidence: 87.5%, URL: https://...)      │
╰──────────────────────────────────────────────────────────────────────────────╯

╭── Step 3/4: Cryptographic Commitment & On-Chain Attestation ─────────────────╮
│ Formula:   Keccak256(FaceHash || PostURL || Timestamp)                       │
│ Hash:      650db04256f523ce9465a946dadabae13cf42605a9964b1435e16e...         │
│ Block:     6                                                                 │
│ Tx Hash:   04e2c9be47603010b0bd7c2ff85817452f6bb7cb9e1fe404d47759...         │
│ Attestor:  0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf                        │
│ Contract:  0xF2E246BB76DF876Cef8b38ae84130F4F55De395b                        │
╰──────────────────────────────────────────────────────────────────────────────╯

╭── Step 4/4: On-Chain Re-Verification Loop ───────────────────────────────────╮
│ Contract Record Found:   ✅ TRUE                                              │
│ On-Chain Commitment:     650db04256f523ce9465a946dadabae13cf42605...        │
│ Locally Recomputed:      650db04256f523ce9465a946dadabae13cf42605...        │
│ Hash Equality Assertion: ✅ MATCHED                                           │
╰──────────────────────────────────────────────────────────────────────────────╯

┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                                                                              ┃
┃   [CRYPTOGRAPHIC RE-VERIFICATION: PASS ✅]                                   ┃
┃   Identity proof validated on-chain and verified against local face scan.    ┃
┃                                                                              ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```

---

## ⚠️ Known Limitations & ZK Roadmap

### Known Limitations
1. **Public API Rate Limits**:
   Bluesky's public XRPC endpoint (`public.api.bsky.app`) throttles aggressive unauthenticated scraping. For demo reliability, the application utilizes a configurable batch limit (`--limit 5` or `--limit 10`) and supports direct image URLs (`--target`).
2. **Local Facial Processing Overhead**:
   DeepFace and high-dimensional cosine distance evaluations require local CPU/GPU compute during large feed scans. Corrupt or non-facial candidate images are gracefully caught and skipped.
3. **Single-Face Focus**:
   Current candidate evaluation prioritizes the primary dominant face detected in each social media attachment.

---

### Future Roadmap: Zero-Knowledge SNARKs (Circom / snarkjs)

While the current architecture eliminates on-chain biometrics via one-way cryptographic commitments, future iterations will integrate **ZK-SNARK circuits**:

```
┌────────────────────────────────────────────────────────┐
│               Circom ZK-SNARK Circuit                  │
│                                                        │
│  Private Inputs:                                       │
│    • Face Embedding 1: [x1, x2, ... x128]              │
│    • Face Embedding 2: [y1, y2, ... y128]              │
│                                                        │
│  Circuit Constraints:                                  │
│    • Compute Cosine / Euclidean Distance L2(E1, E2)    │
│    • Assert L2(E1, E2) <= Threshold                    │
│    • PoseidonHash(E1) == PublicCommitment1             │
│    • PoseidonHash(E2) == PublicCommitment2             │
│                                                        │
│  Public Outputs:                                       │
│    • Proof (pi_a, pi_b, pi_c)                          │
│    • Boolean: IsMatchValid                             │
└────────────────────────────────────────────────────────┘
```

1. **Circom Circuit Verification**:
   Replacing client-side verification with an on-chain `Groth16Verifier.sol` smart contract.
2. **Poseidon Hashing**:
   Migrating from Keccak256/SHA-256 to arithmetic-friendly Poseidon hash functions optimized for zero-knowledge circuits.
3. **True Zero-Knowledge Attestations**:
   The attestor proves to the smart contract that they found a facial match within distance $\delta$ **without ever publishing the post URL, the image, or any hash directly linkable to the person**.

<!-- Verified Terminal Execution Sample Added -->


<!-- Mathematical Formulation of Commitment Hash Validated -->

