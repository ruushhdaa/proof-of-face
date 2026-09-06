def assert_commitment_parity(local_hash, onchain_hash):
    assert local_hash == onchain_hash, 'Attestation mismatch'

