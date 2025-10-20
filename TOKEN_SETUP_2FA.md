# Getting Garmin Tokens WITH 2FA Enabled (iPad-Friendly)

If you have 2FA enabled on your Garmin account (and can't disable it), you need to extract tokens from an already-authenticated browser session.

## 🎯 Method: Extract Tokens from Browser

This works because you'll log into Garmin Connect normally (with 2FA), then grab the tokens the browser is using.

---

## 📱 For iPad Safari Users

### Step 1: Enable Web Inspector on iPad

1. Open **Settings** on iPad
2. Go to **Safari** → **Advanced**
3. Enable **"Web Inspector"** toggle

### Step 2: Connect iPad to Mac (if available)

If you have a Mac available:
1. Connect iPad to Mac with cable
2. On Mac: Open Safari → Develop menu → Select your iPad
3. Continue to Step 3 below

**Don't have a Mac?** Jump to "Alternative: Desktop Browser Method" below.

### Step 3: Log Into Garmin Connect

1. On iPad Safari, go to: https://connect.garmin.com/
2. Log in with your credentials (complete 2FA as normal)
3. Make sure you're fully logged in - you should see your dashboard

### Step 4: Open Developer Tools (on Mac)

1. On Mac Safari: **Develop** → **[Your iPad]** → **connect.garmin.com**
2. This opens the Web Inspector for your iPad browser
3. Click the **Storage** tab
4. Look under **Local Storage** → **connect.garmin.com**

### Step 5: Find the Tokens

Look for keys that contain:
- `oauth_token`
- `oauth1_token`
- `access_token`
- `refresh_token`

Copy the values - these are your tokens!

---

## 💻 Alternative: Desktop Browser Method (Easier!)

**This is the easiest way if you have access to ANY desktop computer:**

### Step 1: Open Chrome/Edge on Desktop

1. Go to: https://connect.garmin.com/
2. Log in (complete 2FA)
3. Press **F12** to open Developer Tools
4. Click the **Application** tab (or **Storage** in Firefox)

### Step 2: Navigate to Storage

In Chrome/Edge:
- **Application** → **Storage** → **Local Storage** → **https://connect.garmin.com**

In Firefox:
- **Storage** → **Local Storage** → **https://connect.garmin.com**

### Step 3: Find OAuth Tokens

Look for entries containing:
- `com.garmin.connect.auth.token`
- `OAuth`
- `access_token`
- `refresh_token`

Copy all values that look like tokens (long random strings).

---

## 🚀 Better Solution: Use the Python Helper

Actually, there's an easier way! Let me create a Python script that can handle 2FA...

**Try this Colab notebook instead:**

I'll create an updated version that uses Garmin's web OAuth flow with 2FA support. Give me a moment to build this for you.

---

## ⚠️ Current Limitation

The `garth` library we're using doesn't natively support 2FA login. We're working on a better solution for you.

**In the meantime:** If you can access a desktop browser, the desktop method above is your best bet to extract tokens manually.
