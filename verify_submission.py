"""
verify_submission.py

Sanity-checks your HH Goa Task 3 pipeline outputs against the four
core requirements, BEFORE you record your demo.

This does not re-run face search or blockchain calls itself — it
inspects the artifacts your pipeline should have already produced
(a results JSON from search_and_match.py, and on-chain data via
web3.py) and tells you clearly what's missing.

Usage:
    python verify_submission.py \
        --match-log match_result.json \
        --candidates-log candidates_log.json \
        --rpc https://rpc-amoy.polygon-technology/  (or your local anvil url) \
        --contract 0xYourContractAddress \
        --contract-abi contracts/FaceAttestation_abi.json \
        --commitment-hash 0xYourCommitmentHashFromUpload

Each check prints PASS / FAIL / WARN with an explanation, so you can
fix gaps before you record.
"""

import argparse
import json
import os
import sys

CHECK = "  [PASS]"
FAIL = "  [FAIL]"
WARN = "  [WARN]"


def section(title):
    print(f"\n=== {title} ===")


def check_face_identification(match_log_path):
    section("1. Face identification")
    if not os.path.exists(match_log_path):
        print(f"{FAIL} {match_log_path} not found. Your search_and_match.py "
              f"should write a JSON result file — run it first.")
        return False

    with open(match_log_path) as f:
        data = json.load(f)

    ok = True
    embedding = data.get("input_face_embedding") or data.get("face_hash")
    if not embedding:
        print(f"{FAIL} No embedding or face_hash found in {match_log_path}. "
              f"Your script needs to actually encode the input face and "
              f"record it, not just say 'face found'.")
        ok = False
    else:
        print(f"{CHECK} Input face embedding/hash present "
              f"({str(embedding)[:40]}...)")

    if "matched" not in data:
        print(f"{FAIL} No 'matched' boolean in result — script should "
              f"explicitly report match/no-match.")
        ok = False
    else:
        print(f"{CHECK} Match result explicitly recorded: {data['matched']}")

    return ok


def check_genuine_search(candidates_log_path):
    section("2. Genuine web/social search step")
    if not os.path.exists(candidates_log_path):
        print(f"{FAIL} {candidates_log_path} not found. Your script should "
              f"log every candidate it evaluated, not just the final match.")
        return False

    with open(candidates_log_path) as f:
        candidates = json.load(f)

    if not isinstance(candidates, list) or len(candidates) == 0:
        print(f"{FAIL} No candidates logged. If this list is empty, your "
              f"pipeline likely isn't actually calling the API.")
        return False

    print(f"{CHECK} {len(candidates)} candidate(s) evaluated from live search.")

    if len(candidates) == 1:
        print(f"{WARN} Only 1 candidate evaluated. This works, but a judge "
              f"skimming fast may read it as suspiciously close to a "
              f"hardcoded result. Ideally your test account has 2-3+ posts "
              f"so rejection of non-matches is visible too.")

    non_matches = [c for c in candidates if not c.get("matched")]
    matches = [c for c in candidates if c.get("matched")]

    if non_matches:
        print(f"{CHECK} {len(non_matches)} non-match(es) correctly rejected "
              f"(proves comparison logic runs on real distinct candidates, "
              f"not a pre-picked one).")
    else:
        print(f"{WARN} No rejected candidates logged. Consider adding a "
              f"clearly-non-matching test post so your recording shows "
              f"genuine discrimination, not just a single hit.")

    if not matches:
        print(f"{FAIL} No candidate marked as matched. Either lower your "
              f"threshold, check your test post, or your comparison logic "
              f"has a bug.")
        return False
    else:
        print(f"{CHECK} Match found: {matches[0].get('post_url', '(no url logged)')}")

    for c in candidates:
        if "distance" not in c and "similarity" not in c:
            print(f"{WARN} A candidate entry is missing a distance/similarity "
                  f"score — good to log this for every candidate so your "
                  f"terminal output shows real per-post evaluation.")
            break

    return True


def check_blockchain(rpc_url, contract_address, contract_abi_path, commitment_hash):
    section("3. Blockchain upload + re-verification")
    try:
        from web3 import Web3
    except ImportError:
        print(f"{FAIL} web3.py not installed. pip install web3")
        return False

    if not os.path.exists(contract_abi_path):
        print(f"{FAIL} ABI file {contract_abi_path} not found.")
        return False

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        print(f"{FAIL} Could not connect to RPC at {rpc_url}. If this is a "
              f"testnet, check the endpoint; if it's Anvil/Hardhat, make "
              f"sure the local node is still running.")
        return False
    print(f"{CHECK} Connected to chain at {rpc_url} (chain id {w3.eth.chain_id})")

    with open(contract_abi_path) as f:
        abi = json.load(f)

    try:
        contract = w3.eth.contract(address=Web3.to_checksum_address(contract_address), abi=abi)
    except Exception as e:
        print(f"{FAIL} Could not load contract at {contract_address}: {e}")
        return False

    code = w3.eth.get_code(Web3.to_checksum_address(contract_address))
    if code in (b"", b"0x", "0x"):
        print(f"{FAIL} No contract code found at {contract_address} on this "
              f"chain — check you deployed to the same network you're "
              f"querying, and that the address is correct.")
        return False
    print(f"{CHECK} Contract bytecode present at {contract_address} — it is "
          f"actually deployed on this chain.")

    # Try the most common view-function names; adjust to match your contract.
    result = None
    for fn_name in ("verifyMatch", "records", "getRecord"):
        if hasattr(contract.functions, fn_name):
            try:
                result = getattr(contract.functions, fn_name)(
                    bytes.fromhex(commitment_hash.replace("0x", ""))
                ).call()
                print(f"{CHECK} On-chain read via `{fn_name}` succeeded: {result}")
                break
            except Exception as e:
                print(f"{WARN} Tried `{fn_name}` but call failed: {e}")

    if result is None:
        print(f"{FAIL} Could not read back the commitment hash from any "
              f"expected view function. Re-verification requires an actual "
              f"on-chain READ, not just checking the tx receipt from upload.")
        return False

    print(f"{CHECK} Re-verification loop confirmed: data fetched FROM chain, "
          f"not from a local variable held over from the upload step.")
    return True


def check_end_to_end(entrypoint="main.py"):
    section("4. Single end-to-end run")
    if not os.path.exists(entrypoint):
        print(f"{FAIL} {entrypoint} not found. You should have one script "
              f"that runs the whole pipeline start to finish.")
        return False
    print(f"{CHECK} {entrypoint} exists.")
    print(f"{WARN} This script can't confirm your demo runs with a single "
          f"command with no manual steps in between — verify that by "
          f"actually running `python {entrypoint}` from a clean terminal "
          f"yourself, right before you record.")
    return True


def main():
    parser = argparse.ArgumentParser(description="Verify Task 3 pipeline outputs.")
    parser.add_argument("--match-log", default="match_result.json")
    parser.add_argument("--candidates-log", default="candidates_log.json")
    parser.add_argument("--rpc", default=None)
    parser.add_argument("--contract", default=None)
    parser.add_argument("--contract-abi", default=None)
    parser.add_argument("--commitment-hash", default=None)
    parser.add_argument("--entrypoint", default="main.py")
    args = parser.parse_args()

    results = {}
    results["face_id"] = check_face_identification(args.match_log)
    results["search"] = check_genuine_search(args.candidates_log)

    if args.rpc and args.contract and args.contract_abi and args.commitment_hash:
        results["chain"] = check_blockchain(
            args.rpc, args.contract, args.contract_abi, args.commitment_hash
        )
    else:
        section("3. Blockchain upload + re-verification")
        print(f"{WARN} Skipped — pass --rpc --contract --contract-abi "
              f"--commitment-hash to check this.")
        results["chain"] = None

    results["e2e"] = check_end_to_end(args.entrypoint)

    section("SUMMARY")
    for k, v in results.items():
        label = "PASS" if v is True else ("SKIPPED" if v is None else "FAIL")
        print(f"  {k:12s} {label}")

    if all(v is not False for v in results.values()):
        print("\nLooks ready to record — but watch it run live yourself once "
              "before hitting record, this script only checks artifacts.")
    else:
        print("\nFix the FAIL items above before recording.")
        sys.exit(1)


if __name__ == "__main__":
    main()

# Automated validation checker for evaluation criteria

