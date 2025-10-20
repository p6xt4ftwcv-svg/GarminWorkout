# Getting Fresh Garmin OAuth Tokens

Your Garmin OAuth tokens expire periodically. When you see **401 Unauthorized** errors, you need fresh tokens.

## 🚀 Quick Setup (5 minutes)

### Step 1: Run the Token Generator Locally

```bash
# Install dependencies (if not already installed)
pip install -r requirements.txt

# Run the token generator
python get_tokens.py
```

### Step 2: Enter Your Garmin Credentials

When prompted, enter:
- Your Garmin Connect email
- Your Garmin Connect password

**Note:** If you have 2FA (two-factor authentication) enabled on Garmin, you may need to temporarily disable it.

### Step 3: Copy the Tokens

The script will output 4 tokens like this:

```
GARMIN_OAUTH_ACCESS_TOKEN=abc123...
GARMIN_OAUTH_REFRESH_TOKEN=xyz789...
GARMIN_OAUTH1_TOKEN=token123...
GARMIN_OAUTH1_TOKEN_SECRET=secret456...
```

### Step 4: Update Railway Environment Variables

1. Go to your Railway dashboard: https://railway.app/dashboard
2. Click on your **GarminWorkout** service
3. Go to the **Variables** tab
4. Update each of the 4 variables with the new values
5. Railway will automatically redeploy

### Step 5: Test!

Once Railway finishes deploying (1-2 minutes):

1. Visit: `https://your-app.up.railway.app/test-auth`
2. Should show: `{"success": true, ...}`
3. Try creating a workout: `5 miles easy`

---

## 🔒 Security Notes

- ⚠️ **NEVER commit tokens to git**
- The `tokens.json` file is in `.gitignore` for safety
- Tokens are personal - don't share them
- If tokens leak, regenerate immediately

---

## 🔄 Token Expiration

- **Access Token**: ~1 hour (auto-refreshed)
- **Refresh Token**: ~30 days
- **OAuth1 Tokens**: Longer-lived

When refresh tokens expire, re-run `get_tokens.py` to get fresh ones.

---

## ❓ Troubleshooting

### "401 Unauthorized" errors
→ Tokens expired. Run `get_tokens.py` again.

### "Two-factor authentication required"
→ Temporarily disable 2FA on Garmin Connect, get tokens, then re-enable.

### "Invalid credentials"
→ Double-check your Garmin email/password.

### Script hangs or times out
→ Check your internet connection and try again.
