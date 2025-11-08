# Secure Local Storage Feature

## Overview

The AI Form Filler now includes **encrypted local storage** with fuzzy field matching for auto-filling form fields. Your data is stored locally on your machine with AES encryption.

## Features

✅ **AES-128 Encryption** - Data encrypted with Fernet (AES-128 CBC mode)  
✅ **Password Protected** - Uses PBKDF2 key derivation with 480,000 iterations  
✅ **Fuzzy Matching** - Automatically matches similar field names (e.g., "Email" matches "Email Address")  
✅ **Local Only** - No cloud storage, all data stays on your machine  
✅ **Session-Based** - Password stored only in memory during session  

## How to Use

### 1. Set Up Storage Password

1. Open the sidebar (look for 🔒 **Secure Storage**)
2. Enter a password in the "Storage Password" field
3. The password is used to encrypt/decrypt your data

### 2. Fill Out a Form

- Upload a PDF and fill out the form as usual
- If you've stored data before, fields will auto-fill with matching values
- Check the **"💾 Save responses to encrypted storage"** checkbox before confirming

### 3. Auto-Fill Next Time

- Next time you upload a form, unlock storage with your password
- Fields will automatically suggest stored values
- Works in both Form Mode and Chat Mode

## Storage Location

Data is stored in: `~/.aiformfiller/`
- `profile.enc` - Encrypted field data
- `salt.key` - Cryptographic salt for key derivation

## Security Notes

⚠️ **Important**:
- Your password is NOT stored anywhere
- If you forget your password, you cannot recover the data
- Deleting storage is permanent and irreversible
- Data is only accessible from your local machine

## Fuzzy Matching Examples

The system intelligently matches field labels:

| Form Field | Stored As | Match? |
|------------|-----------|--------|
| Name | Full Name | ✓ |
| Email | Email Address | ✓ |
| Phone | Phone Number | ✓ |
| Street | Street Address | ✓ |
| Birth Date | Date of Birth | ✓ |

## Managing Storage

### View Stored Fields
- Expand "📋 Stored Fields" in the sidebar
- Shows all field labels and truncated values

### Delete All Data
- Click "🗑️ Delete All Data" button
- Removes both encrypted data and salt
- Cannot be undone!

### Lock Storage
- Click "🔒 Lock Storage" to clear password from memory
- Data remains on disk, encrypted
- Re-enter password to unlock

## Implementation Details

### Files Created
- `aiformfiller/storage.py` - SecureStorage class with encryption
- Updated `app.py` - Integrated storage UI and auto-fill
- Updated `requirements.txt` - Added `cryptography` and `rapidfuzz`

### Dependencies
```
cryptography>=41.0.0  # For Fernet encryption
rapidfuzz>=3.0.0      # For fuzzy string matching
```

## Troubleshooting

**Q: Fields aren't auto-filling**  
A: Make sure you've unlocked storage with the correct password

**Q: "Invalid password" error**  
A: Either wrong password, or starting a new profile (will accept any password)

**Q: Fuzzy matching not working well**  
A: Exact matches always work. Fuzzy matches require >70% similarity

**Q: Want to start fresh**  
A: Use "Delete All Data" button, then set a new password

## Privacy

✓ Data never leaves your computer  
✓ Encrypted at rest with military-grade encryption  
✓ Password never stored on disk  
✓ No telemetry or analytics  

---

**Enjoy secure, private auto-filling!** 🔒✨
