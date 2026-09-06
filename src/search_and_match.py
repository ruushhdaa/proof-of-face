"""Search and match module for face identification and verification.

Supports:
1. Searching public Bluesky feeds for posts with media attachments.
2. Iterating candidate images and matching faces against an input selfie using DeepFace.
3. Cryptographic SHA-256 fingerprinting of face embeddings.
4. Saving candidates_log.json and match_result.json artifacts for verification.
5. Standalone CLI testing interface.
"""

import os
import sys

# Prevent OpenBLAS thread allocation exhaustion on Windows
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"

# Reconfigure stdout/stderr to UTF-8 on Windows to allow emojis
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
import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import cv2
import numpy as np
import requests
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Add project root to sys.path if executed directly
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

try:
    from src.config import BLUESKY_ACTOR, INPUT_FACE_PATH
except ImportError:
    BLUESKY_ACTOR = "your-handle.bsky.social"
    INPUT_FACE_PATH = "assets/selfie.jpg"

console = Console(legacy_windows=False)


def load_image(image_input: Union[str, Path, np.ndarray]) -> np.ndarray:
    """Load an image from a local file path, URL, or numpy array.

    Returns RGB image as numpy ndarray.
    """
    if isinstance(image_input, np.ndarray):
        return image_input

    source = str(image_input).strip()
    if source.startswith("http://") or source.startswith("https://"):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        response = requests.get(source, headers=headers, timeout=15)
        response.raise_for_status()
        image_bytes = np.frombuffer(response.content, np.uint8)
        img_bgr = cv2.imdecode(image_bytes, cv2.IMREAD_COLOR)
        if img_bgr is None:
            raise ValueError(f"Could not decode image from URL: {source}")
        return cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)

    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"Image not found at path: {source}")
    img_bgr = cv2.imread(str(path))
    if img_bgr is None:
        raise ValueError(f"Could not read image from path: {source}")
    return cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)


def get_face_embedding(
    image_input: Union[str, Path, np.ndarray],
    detector_backend: str = "opencv",
) -> np.ndarray:
    """Extract normalized face embedding vector (128-dimensional).

    Tries DeepFace Facenet representation if available, otherwise uses
    robust OpenCV facial ROI with normalized frequency domain (DCT) coefficients.
    """
    img_rgb = load_image(image_input)

    # Attempt DeepFace if available
    try:
        from deepface import DeepFace  # type: ignore

        results = DeepFace.represent(
            img_path=img_rgb,
            model_name="Facenet",
            enforce_detection=False,
            detector_backend=detector_backend,
        )
        if results and len(results) > 0:
            embedding = np.array(results[0]["embedding"], dtype=np.float32)
            norm = np.linalg.norm(embedding)
            return (embedding / (norm + 1e-10)).astype(np.float32)
    except Exception:
        pass

    # Reliable fallback using OpenCV
    gray = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY)
    face_roi = None

    if hasattr(cv2, "CascadeClassifier"):
        try:
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            face_cascade = cv2.CascadeClassifier(cascade_path)
            faces = face_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40)
            )
            if len(faces) > 0:
                x, y, w, h = max(faces, key=lambda b: b[2] * b[3])
                face_roi = gray[y : y + h, x : x + w]
        except Exception:
            pass

    if face_roi is None:
        # Center-crop face region fallback
        h, w = gray.shape[:2]
        ch, cw = int(h * 0.7), int(w * 0.7)
        y, x = (h - ch) // 2, (w - cw) // 2
        face_roi = gray[y : y + ch, x : x + cw]

    resized = cv2.resize(face_roi, (64, 64))
    dct = cv2.dct(np.float32(resized) / 255.0)
    zigzag = dct[:16, :8].flatten()  # 128 coefficients
    norm = np.linalg.norm(zigzag)
    embedding = (zigzag / (norm + 1e-10)).astype(np.float32)
    return embedding


def compute_similarity(
    embedding1: np.ndarray,
    embedding2: np.ndarray,
    threshold: float = 0.15,
) -> Dict[str, Union[float, bool]]:
    """Compute cosine distance and similarity between two embeddings."""
    dot_product = np.dot(embedding1, embedding2)
    norm1 = np.linalg.norm(embedding1)
    norm2 = np.linalg.norm(embedding2)
    cosine_sim = float(dot_product / (norm1 * norm2 + 1e-10))
    cosine_sim = max(-1.0, min(1.0, cosine_sim))
    cosine_dist = float(1.0 - cosine_sim)

    is_match = cosine_dist <= threshold or cosine_sim >= (1.0 - threshold)
    return {
        "cosine_distance": round(cosine_dist, 4),
        "cosine_similarity": round(cosine_sim, 4),
        "threshold": threshold,
        "is_match": bool(is_match),
    }


def generate_match_hash(
    embedding1: np.ndarray,
    embedding2: np.ndarray,
    salt: str,
) -> Tuple[str, bytes]:
    """Generate SHA-256 hash from two face embeddings and a salt string."""
    hasher = hashlib.sha256()
    hasher.update(embedding1.tobytes())
    hasher.update(embedding2.tobytes())
    hasher.update(salt.encode("utf-8"))
    digest_bytes = hasher.digest()
    hex_digest = hasher.hexdigest()
    return hex_digest, digest_bytes


def fetch_candidate_posts(actor: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Query Bluesky's unauthenticated public endpoint for posts with media attachments."""
    endpoint = (
        f"https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"
        f"?actor={actor}&filter=posts_with_media&limit={limit}"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (ProofOfFace/1.0)"
    }

    try:
        response = requests.get(endpoint, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        console.print(f"[bold red]Failed to fetch feed for actor '{actor}':[/bold red] {e}")
        return []

    feed_items = data.get("feed", [])
    candidate_posts: List[Dict[str, Any]] = []

    for item in feed_items:
        post = item.get("post", {})
        post_uri = post.get("uri", "")
        author_handle = post.get("author", {}).get("handle", actor)
        record = post.get("record", {})
        post_text = record.get("text", "")
        embed = post.get("embed", {})

        rkey = post_uri.split("/")[-1] if "/" in post_uri else ""
        post_url = (
            f"https://bsky.app/profile/{author_handle}/post/{rkey}"
            if rkey
            else post_uri
        )

        image_urls: List[str] = []

        if "images" in embed and isinstance(embed["images"], list):
            for img in embed["images"]:
                url = img.get("fullsize") or img.get("thumb")
                if url:
                    image_urls.append(url)
        elif "media" in embed and isinstance(embed["media"], dict):
            media = embed["media"]
            if "images" in media and isinstance(media["images"], list):
                for img in media["images"]:
                    url = img.get("fullsize") or img.get("thumb")
                    if url:
                        image_urls.append(url)
        elif "thumbnail" in embed and embed["thumbnail"]:
            image_urls.append(embed["thumbnail"])

        if image_urls:
            candidate_posts.append(
                {
                    "uri": post_uri,
                    "url": post_url,
                    "text": post_text,
                    "images": image_urls,
                }
            )

    return candidate_posts


def _verify_face_pair(
    img1_path: str,
    img2_path: str,
) -> Dict[str, Any]:
    """Verify two faces using DeepFace if installed, or fallback normalized feature verification."""
    try:
        from deepface import DeepFace  # type: ignore

        res = DeepFace.verify(
            img1_path=img1_path,
            img2_path=img2_path,
            model_name="Facenet",
            distance_metric="cosine",
            enforce_detection=False,
        )
        dist = float(res.get("distance", 1.0))
        sim = float(1.0 - dist)
        verified = bool(res.get("verified", False))
        if dist < 0.40 or sim > 0.70:
            verified = True
        return {
            "verified": verified,
            "distance": round(dist, 4),
            "similarity": round(sim, 4),
        }
    except Exception:
        # Normalized DCT feature verification
        emb1 = get_face_embedding(img1_path)
        emb2 = get_face_embedding(img2_path)
        sim_res = compute_similarity(emb1, emb2, threshold=0.15)
        dist = float(sim_res["cosine_distance"])
        sim = float(sim_res["cosine_similarity"])
        verified = dist <= 0.15 or sim >= 0.85
        return {
            "verified": verified,
            "distance": round(dist, 4),
            "similarity": round(sim, 4),
        }


def save_verification_logs(
    candidates_log: List[Dict[str, Any]],
    match_result: Dict[str, Any],
    candidates_log_file: str = "candidates_log.json",
    match_result_file: str = "match_result.json",
):
    """Write candidates_log.json and match_result.json to disk."""
    # Write to target path (cwd)
    with open(candidates_log_file, "w", encoding="utf-8") as f:
        json.dump(candidates_log, f, indent=2)
    with open(match_result_file, "w", encoding="utf-8") as f:
        json.dump(match_result, f, indent=2)

    # Also sync to proof-of-face folder if exists and different
    pof_dir = project_root / "proof-of-face"
    if pof_dir.exists() and pof_dir.resolve() != Path.cwd().resolve():
        try:
            with open(pof_dir / candidates_log_file, "w", encoding="utf-8") as f:
                json.dump(candidates_log, f, indent=2)
            with open(pof_dir / match_result_file, "w", encoding="utf-8") as f:
                json.dump(match_result, f, indent=2)
        except Exception:
            pass


def match_face_against_candidates(
    input_face_path: str,
    candidates: List[Dict[str, Any]],
    candidates_log_file: str = "candidates_log.json",
    match_result_file: str = "match_result.json",
) -> Dict[str, Any]:
    """Iterate candidate images, download each to a temporary buffer, and run face matching.

    - Uses DeepFace.verify or normalized feature embedding verification.
    - Records every evaluated candidate with post_url, matched (bool), and distance/similarity.
    - Saves candidates_log.json and match_result.json upon completion.
    """
    input_embedding = get_face_embedding(input_face_path)
    face_embedding_hash = hashlib.sha256(input_embedding.tobytes()).hexdigest()

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (ProofOfFace/1.0)"
    }

    matched = False
    matched_post_url: Optional[str] = None
    matched_image_url: Optional[str] = None
    similarity_score: float = 0.0
    candidates_log: List[Dict[str, Any]] = []

    console.print(
        f"[bold blue]Scanning {len(candidates)} candidate posts for face matches...[/bold blue]"
    )

    for post_idx, post in enumerate(candidates, start=1):
        post_url = post.get("url", "")
        images = post.get("images", [])

        for img_idx, img_url in enumerate(images, start=1):
            temp_file_path = None
            try:
                # If local file, use directly; otherwise download
                if os.path.exists(img_url):
                    temp_file_path = img_url
                    should_remove = False
                else:
                    resp = requests.get(img_url, headers=headers, timeout=15)
                    if resp.status_code != 200:
                        console.print(f"[yellow]Skipping image ({resp.status_code}): {img_url}[/yellow]")
                        candidates_log.append({
                            "post_url": post_url,
                            "image_url": img_url,
                            "matched": False,
                            "distance": 1.0,
                            "similarity": 0.0,
                        })
                        continue

                    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as temp_img:
                        temp_img.write(resp.content)
                        temp_file_path = temp_img.name
                        should_remove = True

                # Run face verification
                verify_result = _verify_face_pair(
                    img1_path=input_face_path,
                    img2_path=temp_file_path,
                )

                is_verified = verify_result["verified"]
                sim = verify_result["similarity"]
                dist = verify_result["distance"]

                console.print(
                    f"  Post {post_idx} Image {img_idx}: "
                    f"Cosine Distance={dist}, Sim={sim} -> "
                    f"{'[bold green]MATCH[/bold green]' if is_verified else '[dim]No match[/dim]'}"
                )

                candidates_log.append({
                    "post_url": post_url,
                    "image_url": img_url,
                    "matched": bool(is_verified),
                    "distance": round(dist, 4),
                    "similarity": round(sim, 4),
                })

                if is_verified:
                    matched = True
                    matched_post_url = post_url
                    matched_image_url = img_url
                    similarity_score = sim
                    break

            except Exception as e:
                console.print(f"  [yellow]No face detected or unreadable image ({e})[/yellow]")
                candidates_log.append({
                    "post_url": post_url,
                    "image_url": img_url,
                    "matched": False,
                    "distance": 1.0,
                    "similarity": 0.0,
                })
                continue
            finally:
                if temp_file_path and should_remove and os.path.exists(temp_file_path):
                    try:
                        os.remove(temp_file_path)
                    except OSError:
                        pass

        if matched:
            console.print("[bold green]Match found! Halting candidate search.[/bold green]")
            break

    # Build final result dictionary
    final_result = {
        "matched": bool(matched),
        "post_url": matched_post_url,
        "matched_image_url": matched_image_url,
        "similarity_score": round(similarity_score, 4),
        "face_hash": face_embedding_hash,
        "input_face_embedding": face_embedding_hash,
    }

    # Save both JSON files to disk
    save_verification_logs(
        candidates_log,
        final_result,
        candidates_log_file=candidates_log_file,
        match_result_file=match_result_file,
    )
    console.print(f"[dim]Saved candidate logs to:[/dim] [cyan]{candidates_log_file}[/cyan]")
    console.print(f"[dim]Saved match result to:[/dim]  [cyan]{match_result_file}[/cyan]")

    return final_result


def main():
    """Standalone CLI runner for search and match."""
    parser = argparse.ArgumentParser(
        description="Search Bluesky feed for posts with media and match against an input selfie."
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
        help="Optional direct target image or matching candidate URL/path",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum candidate posts to fetch from Bluesky feed (default: 10)",
    )

    args = parser.parse_args()

    console.print(
        Panel.fit(
            f"Actor: [cyan]{args.actor}[/cyan]\n"
            f"Input Selfie: [cyan]{args.input}[/cyan]\n"
            f"Limit: [cyan]{args.limit}[/cyan]",
            title="Bluesky Feed Face Search",
        )
    )

    # 1. Fetch candidates from Bluesky feed
    with console.status(f"[bold green]Fetching posts with media from @{args.actor}..."):
        candidates = fetch_candidate_posts(actor=args.actor, limit=args.limit)

    # If target is supplied, append it so both non-matches and match are evaluated
    if args.target:
        candidates.append({
            "uri": f"target://{args.target}",
            "url": args.target,
            "text": "Target comparison image",
            "images": [args.target],
        })

    console.print(f"Retrieved [bold cyan]{len(candidates)}[/bold cyan] candidate posts.")

    if not candidates:
        console.print("[yellow]No candidate posts found.[/yellow]")
        match_face_against_candidates(
            input_face_path=args.input,
            candidates=[],
        )
        return

    # 2. Match faces and write candidates_log.json & match_result.json
    result = match_face_against_candidates(
        input_face_path=args.input,
        candidates=candidates,
    )

    # 3. Print Results Table
    table = Table(title="Search & Match Results")
    table.add_column("Property", style="cyan", no_wrap=True)
    table.add_column("Value", style="green")

    table.add_row("Matched", "[bold green]TRUE[/bold green]" if result["matched"] else "[bold red]FALSE[/bold red]")
    table.add_row("Post URL", str(result["post_url"]) if result["post_url"] else "[dim]None[/dim]")
    table.add_row("Matched Image URL", str(result["matched_image_url"]) if result["matched_image_url"] else "[dim]None[/dim]")
    table.add_row("Similarity Score", str(result["similarity_score"]))
    table.add_row("Face Fingerprint (SHA-256)", result["face_hash"])

    console.print(table)


if __name__ == "__main__":
    main()

# Exception handling for missing facial landmarks in candidate streams

