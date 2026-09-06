"""ProofOfFace: Privacy-Preserving Facial Discovery & Attestation.

CLI Flow:
1. Print banner: "ProofOfFace: Privacy-Preserving Facial Discovery & Attestation"
2. Step 1: Encode local face scan from INPUT_FACE_PATH.
3. Step 2: Query public feed for BLUESKY_ACTOR. Stream evaluation of candidates.
4. Step 3: Construct cryptographic commitment (Keccak256) and push to chain.
5. Step 4: Re-verification loop: fetch from contract and verify assertion.
"""

import os
import sys

# Prevent OpenBLAS thread allocation exhaustion on Windows
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"

# Reconfigure stdout/stderr to UTF-8 on Windows to allow emojis (✅, ❌)
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import argparse
import hashlib
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from rich import box
from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Ensure current directory and package root are in sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.config import BLUESKY_ACTOR, INPUT_FACE_PATH, NETWORK, WEB3_PROVIDER_URI
from src.search_and_match import (
    _verify_face_pair,
    fetch_candidate_posts,
    get_face_embedding,
    load_image,
)
from src.blockchain import BlockchainClient

console = Console(legacy_windows=False)


def print_banner():
    """Print the ProofOfFace application banner."""
    banner_text = Text()
    banner_text.append("ProofOfFace\n", style="bold magenta")
    banner_text.append(
        "Privacy-Preserving Facial Discovery & Attestation",
        style="bold cyan",
    )
    banner_panel = Panel(
        Align.center(banner_text),
        box=box.DOUBLE,
        border_style="bright_blue",
        padding=(1, 2),
    )
    console.print(banner_panel)


def step_1_encode_face(input_path: str) -> str:
    """Step 1: Encode local face scan from input path and compute SHA-256 fingerprint."""
    console.print(
        Panel(
            f"[bold yellow]Step 1/4:[/bold yellow] [bold white]Local Face Scan & Feature Encoding[/bold white]\n"
            f"[dim]Source Image:[/dim] [cyan]{input_path}[/cyan]",
            box=box.ROUNDED,
            border_style="yellow",
        )
    )

    if not Path(input_path).exists():
        console.print(f"[bold red]Error:[/bold red] Input image file not found at: {input_path}")
        sys.exit(1)

    with console.status("[bold green]Scanning and generating normalized face embedding..."):
        embedding = get_face_embedding(input_path)
        face_hash = hashlib.sha256(embedding.tobytes()).hexdigest()

    table = Table(box=box.SIMPLE, show_header=False)
    table.add_column("Property", style="bold cyan")
    table.add_column("Value", style="green")

    table.add_row("Input Scan", str(input_path))
    table.add_row("Embedding Vector", f"128-D Normalized Vector ({embedding.dtype})")
    table.add_row("Face Fingerprint (SHA-256)", face_hash)

    console.print(table)
    console.print()
    return face_hash


def step_2_search_and_match(
    actor: str,
    input_path: str,
    face_hash: Optional[str] = None,
    limit: int = 10,
    threshold: float = 0.40,
    target_override: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Step 2: Query public feed for BLUESKY_ACTOR and stream evaluation of candidates."""
    from src.search_and_match import save_verification_logs

    if not face_hash:
        embedding = get_face_embedding(input_path)
        face_hash = hashlib.sha256(embedding.tobytes()).hexdigest()

    console.print(
        Panel(
            f"[bold yellow]Step 2/4:[/bold yellow] [bold white]Public Feed Query & Candidate Stream Evaluation[/bold white]\n"
            f"[dim]Actor Handle:[/dim] [cyan]@{actor}[/cyan]  |  [dim]Limit:[/dim] [cyan]{limit}[/cyan] posts",
            box=box.ROUNDED,
            border_style="yellow",
        )
    )

    candidates_log: List[Dict[str, Any]] = []

    with console.status(f"[bold green]Fetching posts with media from Bluesky for @{actor}..."):
        candidates = fetch_candidate_posts(actor=actor, limit=limit)

    # If target post/image is provided, append it to candidates stream
    if target_override:
        candidates.append({
            "uri": f"target://{target_override}",
            "url": target_override,
            "text": "Target comparison image",
            "images": [target_override],
        })

    if not candidates:
        console.print(f"[yellow]No posts with media found for actor @{actor}.[/yellow]")
        save_verification_logs(
            [],
            {
                "matched": False,
                "post_url": None,
                "matched_image_url": None,
                "similarity_score": 0.0,
                "face_hash": face_hash,
                "input_face_embedding": face_hash,
            },
        )
        return None

    console.print(
        f"Streaming evaluation across [bold cyan]{len(candidates)}[/bold cyan] candidate posts:\n"
    )

    candidate_num = 0
    matched_candidate = None
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (ProofOfFace/1.0)"
    }

    for post in candidates:
        post_url = post.get("url", "")
        images = post.get("images", [])

        for img_url in images:
            candidate_num += 1
            temp_file_path = None
            try:
                # If local file, use directly; otherwise download
                if os.path.exists(img_url):
                    temp_file_path = img_url
                    should_remove = False
                else:
                    resp = requests.get(img_url, headers=headers, timeout=12)
                    if resp.status_code != 200:
                        console.print(
                            f"  Candidate {candidate_num}: [bold red]❌ Face not detected[/bold red] (HTTP {resp.status_code})"
                        )
                        candidates_log.append({
                            "post_url": post_url,
                            "image_url": img_url,
                            "matched": False,
                            "distance": 1.0,
                            "similarity": 0.0,
                        })
                        continue

                    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                        tmp.write(resp.content)
                        temp_file_path = tmp.name
                        should_remove = True

                # Face verification
                verify_res = _verify_face_pair(input_path, temp_file_path)
                dist = verify_res["distance"]
                sim = verify_res["similarity"]
                conf_pct = sim * 100.0

                candidates_log.append({
                    "post_url": post_url,
                    "image_url": img_url,
                    "matched": bool(verify_res["verified"]),
                    "distance": round(dist, 4),
                    "similarity": round(sim, 4),
                })

                if verify_res["verified"]:
                    console.print(
                        f"  Candidate {candidate_num}: [bold green]✅ Match confirmed![/bold green] "
                        f"(Confidence: [bold cyan]{conf_pct:.1f}%[/bold cyan], URL: [underline]{post_url}[/underline])"
                    )
                    matched_candidate = {
                        "post_url": post_url,
                        "image_url": img_url,
                        "confidence": sim,
                        "confidence_pct": conf_pct,
                        "distance": dist,
                    }
                    break
                else:
                    console.print(
                        f"  Candidate {candidate_num}: [yellow]❌ No match (Distance: {dist:.2f})[/yellow]"
                    )

            except Exception:
                console.print(
                    f"  Candidate {candidate_num}: [bold red]❌ Face not detected[/bold red]"
                )
                candidates_log.append({
                    "post_url": post_url,
                    "image_url": img_url,
                    "matched": False,
                    "distance": 1.0,
                    "similarity": 0.0,
                })
            finally:
                if temp_file_path and should_remove and os.path.exists(temp_file_path):
                    try:
                        os.remove(temp_file_path)
                    except OSError:
                        pass

        if matched_candidate:
            break

    # Save artifacts to disk
    save_verification_logs(
        candidates_log,
        {
            "matched": bool(matched_candidate is not None),
            "post_url": matched_candidate["post_url"] if matched_candidate else None,
            "matched_image_url": matched_candidate.get("image_url") if matched_candidate else None,
            "similarity_score": matched_candidate["confidence"] if matched_candidate else 0.0,
            "face_hash": face_hash,
            "input_face_embedding": face_hash,
        },
    )
    console.print(f"[dim]Saved candidate logs to:[/dim] [cyan]candidates_log.json[/cyan]")
    console.print(f"[dim]Saved match result to:[/dim]  [cyan]match_result.json[/cyan]\n")

    return matched_candidate


def step_3_onchain_attestation(
    client: BlockchainClient,
    face_hash: str,
    post_url: str,
    confidence: float,
) -> Dict[str, Any]:
    """Step 3: Construct cryptographic commitment and record on-chain."""
    console.print(
        Panel(
            f"[bold yellow]Step 3/4:[/bold yellow] [bold white]Cryptographic Commitment & On-Chain Attestation[/bold white]\n"
            f"[dim]Network:[/dim] [cyan]{client.network.upper()}[/cyan]  |  "
            f"[dim]Contract:[/dim] [cyan]{client.contract_address}[/cyan]",
            box=box.ROUNDED,
            border_style="yellow",
        )
    )

    timestamp = int(time.time())
    commitment = client.create_commitment(face_hash, post_url, timestamp)

    with console.status("[bold green]Broadcasting attestation transaction to blockchain..."):
        tx_hash = client.record_match_on_chain(commitment, post_url, confidence)
        tx_info = client.get_tx_details(tx_hash)

    table = Table(box=box.SIMPLE, show_header=False)
    table.add_column("Property", style="bold cyan")
    table.add_column("Value", style="green")

    table.add_row("Commitment Formula", "Keccak256(FaceHash || PostURL || Timestamp)")
    table.add_row("Commitment Hash", commitment.hex())
    table.add_row("Block Number", str(tx_info["block_number"]))
    table.add_row("Tx Hash", tx_hash)
    table.add_row("Attestor Address", tx_info["attestor"])
    table.add_row("Target Contract", client.contract_address)
    table.add_row("Block Timestamp", str(timestamp))

    console.print(table)
    console.print()

    return {
        "commitment": commitment,
        "commitment_hex": commitment.hex(),
        "timestamp": timestamp,
        "tx_hash": tx_hash,
        "block_number": tx_info["block_number"],
        "attestor": tx_info["attestor"],
    }


def step_4_reverification_loop(
    client: BlockchainClient,
    face_hash: str,
    local_post_url: str,
    local_timestamp: int,
    original_commitment: Any,
) -> bool:
    """Step 4: Pull commitment from smart contract and assert local re-computation."""
    console.print(
        Panel(
            f"[bold yellow]Step 4/4:[/bold yellow] [bold white]On-Chain Re-Verification Loop[/bold white]\n"
            f"[dim]Asserting:[/dim] [cyan]local_commitment == on_chain_commitment[/cyan]",
            box=box.ROUNDED,
            border_style="yellow",
        )
    )

    with console.status("[bold green]Querying smart contract for recorded attestation..."):
        on_chain_record = client.verify_match_on_chain(original_commitment)

    # Re-compute commitment locally from downloaded post data & original timestamp
    local_recomputed = client.create_commitment(
        face_hash, on_chain_record["post_url"], local_timestamp
    )

    norm_orig = str(original_commitment.hex() if hasattr(original_commitment, "hex") else original_commitment).replace("0x", "").lower()
    norm_local = str(local_recomputed.hex() if hasattr(local_recomputed, "hex") else local_recomputed).replace("0x", "").lower()
    norm_chain = str(on_chain_record["commitment_hash"]).replace("0x", "").lower()

    # Cryptographic assertions
    is_exists = on_chain_record["exists"]
    is_hash_match = (norm_local == norm_chain) and (norm_local == norm_orig)

    reverification_passed = is_exists and is_hash_match

    table = Table(box=box.SIMPLE, show_header=False)
    table.add_column("Check", style="bold cyan")
    table.add_column("Result", style="green")

    table.add_row("Contract Record Found", "✅ TRUE" if is_exists else "❌ FALSE")
    table.add_row("On-Chain Commitment", norm_chain)
    table.add_row("Locally Recomputed", norm_local)
    table.add_row("Hash Equality Assertion", "✅ MATCHED" if is_hash_match else "❌ MISMATCH")

    console.print(table)
    console.print()

    if reverification_passed:
        pass_panel = Panel(
            Align.center(
                Text(
                    "[CRYPTOGRAPHIC RE-VERIFICATION: PASS ✅]\n"
                    "Identity proof validated on-chain and verified against local face scan.",
                    style="bold green",
                )
            ),
            box=box.HEAVY,
            border_style="bold green",
            padding=(1, 2),
        )
        console.print(pass_panel)
        return True
    else:
        fail_panel = Panel(
            Align.center(
                Text(
                    "[CRYPTOGRAPHIC RE-VERIFICATION: FAILED ❌]\n"
                    "On-chain commitment hash does not match locally recomputed proof.",
                    style="bold red",
                )
            ),
            box=box.HEAVY,
            border_style="bold red",
            padding=(1, 2),
        )
        console.print(fail_panel)
        return False


def main():
    parser = argparse.ArgumentParser(
        description="ProofOfFace: End-to-End Privacy-Preserving Facial Discovery & Attestation"
    )
    parser.add_argument(
        "--network",
        choices=["local", "amoy"],
        default=NETWORK,
        help="Target blockchain network: 'local' (in-memory simulated chain) or 'amoy' (Polygon Amoy Testnet)",
    )
    parser.add_argument(
        "--actor",
        default=BLUESKY_ACTOR,
        help="Bluesky actor/handle (e.g. bsky.app or your-handle.bsky.social)",
    )
    parser.add_argument(
        "--input",
        default=INPUT_FACE_PATH,
        help="Path to input selfie image (default: assets/selfie.jpg)",
    )
    parser.add_argument(
        "--target",
        default=None,
        help="Optional direct target image URL or path (bypasses Bluesky feed search)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum posts to fetch from Bluesky feed (default: 10)",
    )

    args = parser.parse_args()

    # 1. Banner
    print_banner()

    # Initialize Blockchain Client
    client = BlockchainClient(network=args.network)
    console.print(
        f"[dim]Active Network:[/dim] [bold cyan]{client.network.upper()}[/bold cyan]  |  "
        f"[dim]Contract Address:[/dim] [bold cyan]{client.contract_address}[/bold cyan]\n"
    )

    # 2. Step 1: Encode local face scan
    face_hash = step_1_encode_face(args.input)

    # 3. Step 2: Query public feed & stream evaluation of candidates
    match_result = step_2_search_and_match(
        actor=args.actor,
        input_path=args.input,
        face_hash=face_hash,
        limit=args.limit,
        target_override=args.target,
    )

    if not match_result:
        console.print(
            Panel(
                f"[bold red]Pipeline Halted:[/bold red] No matching face found for input selfie in candidate feed.\n"
                f"Tip: You can provide a direct matching image via [cyan]--target <path_or_url>[/cyan] or update [cyan]--actor[/cyan].",
                box=box.ROUNDED,
                border_style="red",
            )
        )
        sys.exit(0)

    # 4. Step 3: Construct cryptographic commitment & push to chain
    attestation = step_3_onchain_attestation(
        client=client,
        face_hash=face_hash,
        post_url=match_result["post_url"],
        confidence=match_result["confidence"],
    )

    # 5. Step 4: Re-verification loop
    success = step_4_reverification_loop(
        client=client,
        face_hash=face_hash,
        local_post_url=match_result["post_url"],
        local_timestamp=attestation["timestamp"],
        original_commitment=attestation["commitment"],
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
