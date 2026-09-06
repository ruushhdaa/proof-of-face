// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title FaceAttestation
 * @dev Records and verifies cryptographic commitments for face matches on-chain.
 */
contract FaceAttestation {
    struct Attestation {
        bytes32 commitmentHash;
        string postUrl;
        uint256 confidence;
        uint256 timestamp;
        address attestor;
    }

    mapping(bytes32 => Attestation) public attestations;

    event AttestationRecorded(
        bytes32 indexed commitmentHash,
        address indexed attestor,
        uint256 timestamp
    );

    /**
     * @notice Records a new face match attestation.
     * @param commitmentHash Keccak256 commitment hash of (face_hash, post_url, timestamp).
     * @param postUrl URL of the matched social media post.
     * @param confidence Confidence score represented as a scaled integer (e.g. 9771 for 97.71%).
     */
    function recordAttestation(
        bytes32 commitmentHash,
        string memory postUrl,
        uint256 confidence
    ) external {
        require(commitmentHash != bytes32(0), "Invalid commitment hash");
        require(attestations[commitmentHash].timestamp == 0, "Attestation already exists");

        attestations[commitmentHash] = Attestation({
            commitmentHash: commitmentHash,
            postUrl: postUrl,
            confidence: confidence,
            timestamp: block.timestamp,
            attestor: msg.sender
        });

        emit AttestationRecorded(commitmentHash, msg.sender, block.timestamp);
    }

    /**
     * @notice Verifies whether an attestation exists for a given commitment hash.
     * @param commitmentHash Keccak256 commitment hash.
     * @return exists True if attestation exists.
     * @return postUrl Matched post URL.
     * @return confidence Scaled confidence score.
     * @return timestamp Block timestamp when attestation was recorded.
     */
    function verifyAttestation(bytes32 commitmentHash)
        public
        view
        returns (
            bool exists,
            string memory postUrl,
            uint256 confidence,
            uint256 timestamp
        )
    {
        Attestation memory att = attestations[commitmentHash];
        if (att.timestamp == 0) {
            return (false, "", 0, 0);
        }
        return (true, att.postUrl, att.confidence, att.timestamp);
    }

    /**
     * @notice Alias for verifyAttestation for verification scripts.
     */
    function verifyMatch(bytes32 commitmentHash)
        external
        view
        returns (
            bool exists,
            string memory postUrl,
            uint256 confidence,
            uint256 timestamp
        )
    {
        return verifyAttestation(commitmentHash);
    }

    /**
     * @notice Alias for verifyAttestation for verification scripts.
     */
    function getRecord(bytes32 commitmentHash)
        external
        view
        returns (
            bool exists,
            string memory postUrl,
            uint256 confidence,
            uint256 timestamp
        )
    {
        return verifyAttestation(commitmentHash);
    }
}

// Storage layout optimized for gas alignment

