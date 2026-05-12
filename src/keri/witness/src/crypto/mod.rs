use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use blake3::Hasher;
use ed25519_dalek::{Signature, Signer, SigningKey, VerifyingKey, Verifier};
use rand::rngs::OsRng;
use sha2::{Digest, Sha256, Sha512};

use crate::utils::errors::{WitnessError, WitnessResult};

#[derive(Debug, Clone)]
pub struct KeyPair {
    signing_key: SigningKey,
}

impl KeyPair {
    pub fn generate() -> Self {
        let mut csprng = OsRng;
        let signing_key = SigningKey::generate(&mut csprng);
        Self { signing_key }
    }

    pub fn from_seed(seed: &[u8; 32]) -> Self {
        let signing_key = SigningKey::from_bytes(seed);
        Self { signing_key }
    }

    pub fn from_bytes(bytes: &[u8]) -> WitnessResult<Self> {
        let arr: [u8; 32] = bytes
            .try_into()
            .map_err(|_| WitnessError::crypto("invalid key length: expected 32 bytes"))?;
        Ok(Self { signing_key: SigningKey::from_bytes(&arr) })
    }

    pub fn verifying_key_bytes(&self) -> [u8; 32] {
        self.signing_key.verifying_key().to_bytes()
    }

    pub fn verifying_key_b64(&self) -> String {
        URL_SAFE_NO_PAD.encode(self.verifying_key_bytes())
    }

    pub fn sign(&self, message: &[u8]) -> [u8; 64] {
        self.signing_key.sign(message).to_bytes()
    }

    pub fn sign_b64(&self, message: &[u8]) -> String {
        URL_SAFE_NO_PAD.encode(self.sign(message))
    }

    pub fn aid(&self) -> String {
        let vk = self.verifying_key_bytes();
        let digest = blake3_digest(&vk);
        format!("E{}", URL_SAFE_NO_PAD.encode(digest))
    }
}

pub fn verify_ed25519(
    verifying_key_bytes: &[u8],
    message: &[u8],
    signature_bytes: &[u8],
) -> WitnessResult<()> {
    let key_arr: [u8; 32] = verifying_key_bytes.try_into().map_err(|_| {
        WitnessError::crypto("invalid verifying key length")
    })?;
    let sig_arr: [u8; 64] = signature_bytes.try_into().map_err(|_| {
        WitnessError::crypto("invalid signature length")
    })?;

    let verifying_key = VerifyingKey::from_bytes(&key_arr)
        .map_err(|e| WitnessError::crypto(format!("invalid verifying key: {e}")))?;
    let signature = Signature::from_bytes(&sig_arr);

    verifying_key
        .verify(message, &signature)
        .map_err(|e| WitnessError::crypto(format!("signature verification failed: {e}")))
}

pub fn verify_ed25519_b64(
    verifying_key_b64: &str,
    message: &[u8],
    signature_b64: &str,
) -> WitnessResult<()> {
    let key_bytes = URL_SAFE_NO_PAD
        .decode(verifying_key_b64)
        .map_err(|e| WitnessError::crypto(format!("invalid key encoding: {e}")))?;
    let sig_bytes = URL_SAFE_NO_PAD
        .decode(signature_b64)
        .map_err(|e| WitnessError::crypto(format!("invalid signature encoding: {e}")))?;
    verify_ed25519(&key_bytes, message, &sig_bytes)
}

pub fn blake3_digest(data: &[u8]) -> [u8; 32] {
    let mut hasher = Hasher::new();
    hasher.update(data);
    *hasher.finalize().as_bytes()
}

pub fn blake3_said(data: &[u8]) -> String {
    let digest = blake3_digest(data);
    format!("E{}", URL_SAFE_NO_PAD.encode(digest))
}

pub fn sha256_digest(data: &[u8]) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(data);
    hasher.finalize().into()
}

pub fn sha256_said(data: &[u8]) -> String {
    let digest = sha256_digest(data);
    format!("I{}", URL_SAFE_NO_PAD.encode(digest))
}

pub fn compute_said(event_bytes: &[u8]) -> WitnessResult<String> {
    Ok(blake3_said(event_bytes))
}

pub fn verify_said(event_bytes: &[u8], claimed_said: &str) -> WitnessResult<()> {
    let computed = compute_said(event_bytes)?;
    if computed != claimed_said {
        return Err(WitnessError::crypto(format!(
            "SAID mismatch: computed={computed} claimed={claimed_said}"
        )));
    }
    Ok(())
}

pub struct ReceiptCoupling {
    pub verifier_prefix: String,
    pub signature_b64: String,
}

pub fn issue_receipt(
    key_pair: &KeyPair,
    event_bytes: &[u8],
) -> ReceiptCoupling {
    let said = blake3_said(event_bytes);
    let sig_bytes = key_pair.sign(said.as_bytes());
    ReceiptCoupling {
        verifier_prefix: key_pair.verifying_key_b64(),
        signature_b64: URL_SAFE_NO_PAD.encode(sig_bytes),
    }
}

pub fn cesr_encode_receipt(
    witness_aid: &str,
    said: &str,
    signature_b64: &str,
) -> Vec<u8> {
    let receipt = serde_json::json!({
        "v": "KERI10JSON",
        "t": "rct",
        "d": said,
        "i": witness_aid,
    });
    let mut bytes = serde_json::to_vec(&receipt).unwrap_or_default();
    bytes.push(b'\n');
    bytes.extend_from_slice(signature_b64.as_bytes());
    bytes
}

pub fn decode_b64_key(b64: &str) -> WitnessResult<Vec<u8>> {
    URL_SAFE_NO_PAD
        .decode(b64)
        .map_err(|e| WitnessError::crypto(format!("base64 decode error: {e}")))
}

pub fn encode_b64(data: &[u8]) -> String {
    URL_SAFE_NO_PAD.encode(data)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_keygen_and_sign_verify() {
        let kp = KeyPair::generate();
        let msg = b"test message for signing";
        let sig = kp.sign(msg);
        let vk = kp.verifying_key_bytes();
        assert!(verify_ed25519(&vk, msg, &sig).is_ok());
    }

    #[test]
    fn test_wrong_sig_fails() {
        let kp = KeyPair::generate();
        let kp2 = KeyPair::generate();
        let msg = b"test message";
        let sig = kp2.sign(msg);
        let vk = kp.verifying_key_bytes();
        assert!(verify_ed25519(&vk, msg, &sig).is_err());
    }

    #[test]
    fn test_blake3_said_deterministic() {
        let data = b"deterministic test";
        let s1 = blake3_said(data);
        let s2 = blake3_said(data);
        assert_eq!(s1, s2);
        assert!(s1.starts_with('E'));
    }

    #[test]
    fn test_said_verify() {
        let data = b"some event bytes";
        let said = compute_said(data).unwrap();
        assert!(verify_said(data, &said).is_ok());
        assert!(verify_said(b"different data", &said).is_err());
    }

    #[test]
    fn test_aid_derived_from_key() {
        let kp = KeyPair::generate();
        let aid = kp.aid();
        assert!(aid.starts_with('E'));
        assert!(!aid.is_empty());
    }
}