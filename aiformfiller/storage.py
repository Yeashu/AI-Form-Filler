"""Secure local storage for form field data with encryption."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional, Dict

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

try:
    from rapidfuzz import fuzz
except ImportError:
    fuzz = None

logger = logging.getLogger(__name__)

# Storage directory and file paths
STORAGE_DIR = Path.home() / ".aiformfiller"
SALT_FILE = STORAGE_DIR / "salt.key"
DATA_FILE = STORAGE_DIR / "profile.enc"

# Fuzzy matching threshold (0-100)
FUZZY_THRESHOLD = 70


class StorageError(Exception):
    """Base exception for storage-related errors."""
    pass


class SecureStorage:
    """Handles encrypted local storage of form field data."""

    def __init__(self):
        """Initialize storage, creating necessary directories."""
        STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        self._ensure_salt()

    def _ensure_salt(self) -> None:
        """Ensure a salt file exists for key derivation."""
        if not SALT_FILE.exists():
            import secrets
            salt = secrets.token_bytes(32)
            SALT_FILE.write_bytes(salt)
            logger.info("Created new salt file")

    def _derive_key(self, password: str) -> bytes:
        """Derive encryption key from password using PBKDF2.
        
        Args:
            password: User password for encryption.
            
        Returns:
            32-byte encryption key.
        """
        salt = SALT_FILE.read_bytes()
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            # As of 2023, OWASP recommends at least 310,000 iterations for PBKDF2; using 480,000 for increased security margin.
            iterations=480000,
        )
        return kdf.derive(password.encode())

    def _get_fernet(self, password: str) -> Fernet:
        """Get Fernet cipher from password.
        
        Args:
            password: User password.
            
        Returns:
            Fernet instance for encryption/decryption.
        """
        import base64
        key = self._derive_key(password)
        return Fernet(base64.urlsafe_b64encode(key))

    def save_answers(self, answers: Dict[str, str], password: str) -> None:
        """Save form answers to encrypted storage.
        
        Args:
            answers: Dictionary mapping field labels to values.
            password: Password for encryption.
            
        Raises:
            StorageError: If save operation fails.
        """
        try:
            # Load existing data if present
            existing = {}
            if DATA_FILE.exists():
                try:
                    existing = self.load_answers(password)
                except (InvalidToken, StorageError):
                    logger.warning("Could not decrypt existing data, creating new profile")
                    existing = {}

            # Merge new answers with existing
            existing.update(answers)

            # Encrypt and save
            fernet = self._get_fernet(password)
            json_data = json.dumps(existing, indent=2)
            encrypted = fernet.encrypt(json_data.encode())
            DATA_FILE.write_bytes(encrypted)
            
            logger.info(f"Saved {len(answers)} field(s) to encrypted storage")
        except Exception as e:
            logger.error(f"Failed to save answers: {e}")
            raise StorageError(f"Failed to save data: {e}") from e

    def load_answers(self, password: str) -> Dict[str, str]:
        """Load form answers from encrypted storage.
        
        Args:
            password: Password for decryption.
            
        Returns:
            Dictionary mapping field labels to values.
            
        Raises:
            StorageError: If file doesn't exist or decryption fails.
        """
        if not DATA_FILE.exists():
            return {}

        try:
            fernet = self._get_fernet(password)
            encrypted = DATA_FILE.read_bytes()
            decrypted = fernet.decrypt(encrypted)
            data = json.loads(decrypted.decode())
            
            logger.info(f"Loaded {len(data)} field(s) from encrypted storage")
            return data
        except InvalidToken:
            raise StorageError("Invalid password or corrupted data")
        except Exception as e:
            logger.error(f"Failed to load answers: {e}")
            raise StorageError(f"Failed to load data: {e}") from e

    def get_suggestion(
        self, 
        field_label: str, 
        stored_data: Optional[Dict[str, str]] = None,
        password: Optional[str] = None
    ) -> Optional[str]:
        """Get auto-fill suggestion for a field using fuzzy matching.
        
        Tries exact match first, then fuzzy matching if available.
        
        Args:
            field_label: The label of the field to match.
            stored_data: Pre-loaded stored data (optional, will load if not provided).
            password: Password to load data if stored_data not provided.
            
        Returns:
            Suggested value or None if no match found.
        """
        # Load data if not provided
        if stored_data is None:
            if password is None:
                return None
            try:
                stored_data = self.load_answers(password)
            except StorageError:
                return None

        if not stored_data:
            return None

        # Try exact match first
        if field_label in stored_data:
            logger.debug(f"Exact match for '{field_label}'")
            return stored_data[field_label]

        # Fuzzy matching if rapidfuzz is available
        if fuzz is None:
            logger.debug("Rapidfuzz not available, skipping fuzzy match")
            return None

        # Find best fuzzy match using multiple algorithms for better accuracy
        best_match = None
        best_score = 0

        for stored_label, stored_value in stored_data.items():
            # Use token_set_ratio which handles word order and partial matches well
            token_set = fuzz.token_set_ratio(field_label.lower(), stored_label.lower())
            
            # Also check token_sort_ratio which is stricter about word presence
            token_sort = fuzz.token_sort_ratio(field_label.lower(), stored_label.lower())
            
            # Take average to balance flexibility and precision
            base_score = (token_set + token_sort) / 2
            
            # Check if one string is completely contained in the other (but penalize very short queries)
            if field_label.lower() in stored_label.lower():
                # Give bonus for containment, but penalize if query is too short
                length_ratio = len(field_label) / len(stored_label)
                if length_ratio > 0.4:  # Query is at least 40% of stored label
                    base_score = max(base_score, 85)  # Boost score
            
            # Penalize if there are significant word differences
            # e.g., "Father's Name" should NOT match "Mother's Name"
            # Normalize by removing apostrophes and splitting
            import re
            field_normalized = re.sub(r"['\-]", " ", field_label.lower())
            stored_normalized = re.sub(r"['\-]", " ", stored_label.lower())
            
            field_words = set(field_normalized.split())
            stored_words = set(stored_normalized.split())
            
            # Check for conflicting relationship/person identifiers
            conflict_words = {
                'father', 'mother', 'brother', 'sister', 'son', 'daughter',
                'husband', 'wife', 'parent', 'spouse', 'guardian',
                'first', 'last', 'middle', 'maiden', 'grandfather', 'grandmother'
            }
            
            field_conflicts = field_words & conflict_words
            stored_conflicts = stored_words & conflict_words
            # If both have conflict words but none in common, heavily penalize
            if field_conflicts and stored_conflicts and field_conflicts.isdisjoint(stored_conflicts):
                base_score *= 0.2  # Very heavy penalty for mismatched person identifiers
                base_score *= 0.2  # Very heavy penalty for mismatched person identifiers
            
            score = base_score
            
            if score > best_score:
                best_score = score
                best_match = (stored_label, stored_value)

        if best_score >= FUZZY_THRESHOLD and best_match:
            logger.debug(
                f"Fuzzy match for '{field_label}': '{best_match[0]}' (score: {best_score:.1f})"
            )
            return best_match[1]

        logger.debug(f"No match found for '{field_label}' (best score: {best_score:.1f})")
        return None

    def delete_all_data(self) -> None:
        """Delete all stored data and salt. WARNING: This is irreversible!"""
        try:
            if DATA_FILE.exists():
                DATA_FILE.unlink()
                logger.info("Deleted encrypted data file")
            if SALT_FILE.exists():
                SALT_FILE.unlink()
                logger.info("Deleted salt file")
        except Exception as e:
            logger.error(f"Failed to delete data: {e}")
            raise StorageError(f"Failed to delete data: {e}") from e

    def has_stored_data(self) -> bool:
        """Check if any data is currently stored.
        
        Returns:
            True if encrypted data file exists, False otherwise.
        """
        return DATA_FILE.exists()


def get_storage() -> SecureStorage:
    """Get a SecureStorage instance (convenience factory function).
    
    Returns:
        Initialized SecureStorage instance.
    """
    return SecureStorage()


__all__ = ["SecureStorage", "StorageError", "get_storage"]
