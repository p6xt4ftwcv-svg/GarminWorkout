#!/usr/bin/env python3
"""
Helper script to get Garmin OAuth tokens for Railway deployment
Run this locally to get fresh tokens, then add them to Railway environment variables
"""

import garth
from garth.exc import GarthHTTPError
import json

def get_garmin_tokens():
    """Get OAuth tokens from Garmin using email/password"""

    print("=" * 60)
    print("Garmin OAuth Token Generator")
    print("=" * 60)
    print("\nThis will log into your Garmin account and generate OAuth tokens")
    print("You'll need to enter your Garmin Connect email and password\n")

    # Get credentials
    email = input("Garmin Connect Email: ").strip()
    password = input("Garmin Connect Password: ").strip()

    print("\n🔐 Authenticating with Garmin...")

    try:
        # Login to Garmin
        garth.login(email, password)
        print("✅ Login successful!")

        # Get OAuth2 tokens
        oauth2_token = garth.client.oauth2_token
        print("✅ OAuth2 tokens retrieved")

        # Get OAuth1 tokens
        oauth1_token = garth.client.oauth1_token
        print("✅ OAuth1 tokens retrieved")

        print("\n" + "=" * 60)
        print("🎉 SUCCESS! Copy these tokens to Railway:")
        print("=" * 60)
        print("\nGo to Railway Dashboard → Your Service → Variables")
        print("Add these 4 environment variables:\n")

        print(f"GARMIN_OAUTH_ACCESS_TOKEN={oauth2_token.access_token}")
        print(f"GARMIN_OAUTH_REFRESH_TOKEN={oauth2_token.refresh_token}")
        print(f"GARMIN_OAUTH1_TOKEN={oauth1_token.oauth_token}")
        print(f"GARMIN_OAUTH1_TOKEN_SECRET={oauth1_token.oauth_token_secret}")

        print("\n" + "=" * 60)
        print("\n💾 Saving tokens to tokens.json for backup...")

        tokens = {
            "GARMIN_OAUTH_ACCESS_TOKEN": oauth2_token.access_token,
            "GARMIN_OAUTH_REFRESH_TOKEN": oauth2_token.refresh_token,
            "GARMIN_OAUTH1_TOKEN": oauth1_token.oauth_token,
            "GARMIN_OAUTH1_TOKEN_SECRET": oauth1_token.oauth_token_secret
        }

        with open('tokens.json', 'w') as f:
            json.dump(tokens, f, indent=2)

        print("✅ Tokens saved to tokens.json")
        print("\n⚠️  WARNING: Keep tokens.json private! Don't commit it to git!")
        print("\n📝 Next steps:")
        print("1. Copy the 4 environment variables above")
        print("2. Go to Railway Dashboard")
        print("3. Navigate to your service → Variables tab")
        print("4. Update each variable with the new values")
        print("5. Railway will automatically redeploy with fresh tokens")

    except GarthHTTPError as e:
        print(f"\n❌ Authentication failed: {e}")
        print("\nPossible reasons:")
        print("- Wrong email or password")
        print("- Two-factor authentication enabled (try disabling temporarily)")
        print("- Garmin account locked or requires verification")

    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    get_garmin_tokens()
