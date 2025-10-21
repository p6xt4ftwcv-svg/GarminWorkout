from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import garth
from garminconnect import Garmin
import os
import re
import time
import json
from datetime import datetime
from typing import Optional

app = FastAPI()

# Allow CORS for iOS Shortcuts
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class WorkoutRequest(BaseModel):
    workout_text: str
    workout_name: Optional[str] = None

class WorkoutParser:
    """Parse natural language workout descriptions into Garmin workout structure"""

    def __init__(self):
        self.intensity_map = {
            'warmup': {'stepTypeId': 1, 'stepTypeKey': 'warmup', 'displayOrder': 1},
            'warm up': {'stepTypeId': 1, 'stepTypeKey': 'warmup', 'displayOrder': 1},
            'cooldown': {'stepTypeId': 2, 'stepTypeKey': 'cooldown', 'displayOrder': 2},
            'cool down': {'stepTypeId': 2, 'stepTypeKey': 'cooldown', 'displayOrder': 2},
            'easy': {'stepTypeId': 3, 'stepTypeKey': 'interval', 'displayOrder': 3},
            'recovery': {'stepTypeId': 4, 'stepTypeKey': 'recovery', 'displayOrder': 4},
            'interval': {'stepTypeId': 3, 'stepTypeKey': 'interval', 'displayOrder': 3},
            'tempo': {'stepTypeId': 3, 'stepTypeKey': 'interval', 'displayOrder': 3},
            'threshold': {'stepTypeId': 3, 'stepTypeKey': 'interval', 'displayOrder': 3},
        }
    
    def parse(self, text: str, custom_name: str = None) -> dict:
        """Parse workout text into Garmin workout JSON"""

        # Use custom name if provided, otherwise use the workout text itself
        if custom_name:
            workout_name = custom_name
        else:
            # For multi-line workouts, use just the first line as the name
            first_line = text.strip().split('\n')[0].strip()
            # Remove em-dashes and clean up
            workout_name = first_line.replace('—', '-').capitalize()
            # Limit length to avoid overly long names
            if len(workout_name) > 50:
                workout_name = workout_name[:47] + "..."

        # Create workout structure with all required fields
        workout = {
            "workoutName": workout_name,
            "description": "",  # Required field
            "sportType": {
                "sportTypeId": 1,
                "sportTypeKey": "running"
            },
            "workoutSegments": [{
                "segmentOrder": 1,
                "sportType": {
                    "sportTypeId": 1,
                    "sportTypeKey": "running"
                },
                "workoutSteps": []
            }]
        }
        
        steps = self._parse_steps(text)
        
        for idx, step in enumerate(steps):
            workout["workoutSegments"][0]["workoutSteps"].append(
                self._create_step(idx + 1, step)
            )
        
        return workout
    
    def _parse_steps(self, text: str):
        """Break down text into individual workout steps"""
        steps = []
        text = text.lower()

        # Filter out metadata lines (Target, Notes, etc.)
        lines = text.split('\n')
        filtered_lines = []
        for line in lines:
            # Skip lines that are just metadata
            if line.strip().startswith(('target:', 'notes:', 'expect:', 'finish with')):
                continue
            filtered_lines.append(line)

        # Process each line separately (newlines separate major steps)
        # Then also split each line by commas/semicolons for inline multiple steps
        all_parts = []
        for line in filtered_lines:
            line = line.strip()
            if not line:
                continue
            # Split each line by commas, semicolons, or "then"
            line_parts = re.split(r'[,;]|\bthen\b', line)
            all_parts.extend(line_parts)

        for part in all_parts:
            part = part.strip()
            if not part:
                continue

            # Check for "Repeat X times:" pattern
            repeat_match_times = re.match(r'repeat\s+(\d+)\s+times?\s*:\s*(.+)', part, re.IGNORECASE)
            if repeat_match_times:
                repeats = int(repeat_match_times.group(1))
                inner_text = repeat_match_times.group(2)

                # Parse the inner steps (may contain 2a), 2b) pattern)
                inner_parts = re.split(r'\d+[a-z]\)\s*', inner_text)
                inner_steps = []
                for inner_part in inner_parts:
                    inner_part = inner_part.strip()
                    if inner_part:
                        step = self._parse_single_step(inner_part)
                        if step:
                            inner_steps.append(step)

                if inner_steps:
                    steps.append({
                        'type': 'repeat',
                        'repeats': repeats,
                        'steps': inner_steps
                    })
                continue

            # Check for repeats: "5x(800m @ 5k pace, 400m easy)" or "6x(20 seconds, 100 seconds)"
            repeat_match = re.match(r'(\d+)\s*x\s*\(([^)]+)\)', part)
            if repeat_match:
                repeats = int(repeat_match.group(1))
                inner_text = repeat_match.group(2)
                inner_steps = self._parse_steps(inner_text)

                steps.append({
                    'type': 'repeat',
                    'repeats': repeats,
                    'steps': inner_steps
                })
                continue

            # Parse individual step
            step = self._parse_single_step(part)
            if step:
                steps.append(step)

        return steps
    
    def _parse_single_step(self, text: str):
        """Parse a single step like '10 min warmup' or '800m @ 5k pace'"""

        # Determine intensity/step type
        step_type = {'stepTypeId': 3, 'stepTypeKey': 'interval', 'displayOrder': 3}  # default
        for key, value in self.intensity_map.items():
            if key in text:
                step_type = value
                break

        # Also check for "stride" (high intensity) and "jog/walk" (recovery)
        if 'stride' in text or 'fast' in text:
            step_type = {'stepTypeId': 3, 'stepTypeKey': 'interval', 'displayOrder': 3}
        elif 'jog' in text or 'walk' in text:
            step_type = {'stepTypeId': 4, 'stepTypeKey': 'recovery', 'displayOrder': 4}

        # Parse MM:SS format (like 50:00, 1:40, 0:20)
        time_mmss_match = re.search(r'(\d+):(\d+)', text)
        if time_mmss_match:
            minutes = int(time_mmss_match.group(1))
            seconds = int(time_mmss_match.group(2))
            total_seconds = (minutes * 60) + seconds
            return {
                'type': 'step',
                'step_type': step_type,
                'end_condition': {
                    'conditionTypeId': 2,
                    'conditionTypeKey': 'time',
                    'displayOrder': 2,
                    'displayable': True
                },
                'end_condition_value': total_seconds,
            }

        # Parse seconds (like "20 seconds", "100 sec")
        seconds_match = re.search(r'(\d+(?:\.\d+)?)\s*(sec|second|seconds|secs?)', text)
        if seconds_match:
            seconds = float(seconds_match.group(1))
            return {
                'type': 'step',
                'step_type': step_type,
                'end_condition': {
                    'conditionTypeId': 2,
                    'conditionTypeKey': 'time',
                    'displayOrder': 2,
                    'displayable': True
                },
                'end_condition_value': int(seconds),
            }

        # Parse duration - time based (minutes)
        time_match = re.search(r'(\d+(?:\.\d+)?)\s*(min|minute|minutes|mins?)', text)
        if time_match:
            minutes = float(time_match.group(1))
            return {
                'type': 'step',
                'step_type': step_type,
                'end_condition': {
                    'conditionTypeId': 2,
                    'conditionTypeKey': 'time',
                    'displayOrder': 2,
                    'displayable': True
                },
                'end_condition_value': int(minutes * 60),  # seconds
            }

        # Parse duration - distance based
        distance_match = re.search(r'(\d+(?:\.\d+)?)\s*(m|meter|meters|km|k|mile|miles|mi)', text)
        if distance_match:
            value = float(distance_match.group(1))
            unit = distance_match.group(2)

            # Convert to meters
            if unit in ['km', 'k']:
                meters = value * 1000
            elif unit in ['mile', 'miles', 'mi']:
                meters = value * 1609.34
            else:
                meters = value

            return {
                'type': 'step',
                'step_type': step_type,
                'end_condition': {
                    'conditionTypeId': 3,
                    'conditionTypeKey': 'distance',
                    'displayOrder': 3,
                    'displayable': True
                },
                'end_condition_value': meters,  # meters (not centimeters!)
            }

        # Default: 5 minutes if we can't parse
        return {
            'type': 'step',
            'step_type': step_type,
            'end_condition': {
                'conditionTypeId': 2,
                'conditionTypeKey': 'time',
                'displayOrder': 2,
                'displayable': True
            },
            'end_condition_value': 300,
        }
    
    def _create_step(self, order: int, step_data: dict) -> dict:
        """Create Garmin workout step JSON matching exact API format"""

        if step_data['type'] == 'repeat':
            # Create a repeat step
            repeat_step = {
                "type": "RepeatGroupDTO",
                "stepId": None,
                "stepOrder": order,
                "numberOfIterations": step_data['repeats'],
                "smartRepeat": False,
                "childStepId": 1,
                "workoutSteps": []
            }

            for idx, inner_step in enumerate(step_data['steps']):
                repeat_step["workoutSteps"].append(
                    self._create_step(idx + 1, inner_step)
                )

            return repeat_step

        else:
            # Create ExecutableStepDTO matching Garmin's exact format
            step = {
                "type": "ExecutableStepDTO",
                "stepId": None,
                "stepOrder": order,
                "stepType": step_data['step_type'],
                "childStepId": None,
                "description": None,
                "endCondition": step_data['end_condition'],
                "endConditionValue": step_data['end_condition_value'],
                "preferredEndConditionUnit": None,
                "endConditionCompare": None,
                "targetType": {
                    "workoutTargetTypeId": 1,
                    "workoutTargetTypeKey": "no.target",
                    "displayOrder": 1
                },
                "targetValueOne": None,
                "targetValueTwo": None,
                "targetValueUnit": None,
                "zoneNumber": None,
                "secondaryTargetType": None,
                "secondaryTargetValueOne": None,
                "secondaryTargetValueTwo": None,
                "secondaryTargetValueUnit": None,
                "secondaryZoneNumber": None,
                "endConditionZone": None,
                "strokeType": {
                    "strokeTypeId": 0,
                    "strokeTypeKey": None,
                    "displayOrder": 0
                },
                "equipmentType": {
                    "equipmentTypeId": 0,
                    "equipmentTypeKey": None,
                    "displayOrder": 0
                },
                "category": None,
                "exerciseName": None,
                "workoutProvider": None,
                "providerExerciseSourceId": None,
                "weightValue": None,
                "weightUnit": None
            }

            return step

def authenticate_garmin():
    """Authenticate with Garmin using OAuth tokens from environment variables"""
    print("Starting authentication...")

    # OAuth2 tokens - strip whitespace to prevent header errors
    access_token = os.getenv("GARMIN_OAUTH_ACCESS_TOKEN", "").strip()
    refresh_token = os.getenv("GARMIN_OAUTH_REFRESH_TOKEN", "").strip()

    # OAuth1 tokens (needed for API calls) - strip whitespace
    oauth1_token = os.getenv("GARMIN_OAUTH1_TOKEN", "").strip()
    oauth1_token_secret = os.getenv("GARMIN_OAUTH1_TOKEN_SECRET", "").strip()
    
    print(f"OAuth2 Access Token present: {bool(access_token)}")
    print(f"OAuth2 Refresh Token present: {bool(refresh_token)}")
    print(f"OAuth1 Token present: {bool(oauth1_token)}")
    print(f"OAuth1 Secret present: {bool(oauth1_token_secret)}")
    
    if not access_token or not refresh_token:
        error_msg = "OAuth2 tokens not configured. Please set GARMIN_OAUTH_ACCESS_TOKEN and GARMIN_OAUTH_REFRESH_TOKEN environment variables."
        print(f"ERROR: {error_msg}")
        raise HTTPException(
            status_code=500, 
            detail=error_msg
        )
    
    if not oauth1_token or not oauth1_token_secret:
        error_msg = "OAuth1 tokens not configured. Please set GARMIN_OAUTH1_TOKEN and GARMIN_OAUTH1_TOKEN_SECRET environment variables."
        print(f"ERROR: {error_msg}")
        raise HTTPException(
            status_code=500,
            detail=error_msg
        )
    
    try:
        print("Configuring garth with tokens...")

        # Create temporary directory for garth tokens
        import tempfile
        import os as os_module

        temp_dir = tempfile.mkdtemp()
        print(f"Created temp directory: {temp_dir}")

        # Create oauth1_token.json
        oauth1_data = {
            "oauth_token": oauth1_token,
            "oauth_token_secret": oauth1_token_secret
        }
        oauth1_path = os_module.path.join(temp_dir, "oauth1_token.json")
        with open(oauth1_path, 'w') as f:
            json.dump(oauth1_data, f)
        print("✅ OAuth1 token file created")

        # Create oauth2_token.json
        oauth2_data = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "Bearer",
            "expires_in": 3600,
            "expires_at": int(time.time()) + 3600,
            "refresh_token_expires_in": 2592000,
            "refresh_token_expires_at": int(time.time()) + 2592000,
            "scope": "",
            "jti": "",
            "expired": False,
            "refresh_expired": False
        }
        oauth2_path = os_module.path.join(temp_dir, "oauth2_token.json")
        with open(oauth2_path, 'w') as f:
            json.dump(oauth2_data, f)
        print("✅ OAuth2 token file created")

        # Create domain.txt
        domain_path = os_module.path.join(temp_dir, "domain.txt")
        with open(domain_path, 'w') as f:
            f.write("garmin.com")
        print("✅ Domain file created")

        # Resume garth session from the temporary directory
        garth.resume(temp_dir)
        print("✅ Garth session resumed successfully!")

        # Now create Garmin client - it will automatically use the configured garth.client
        print("Creating Garmin client...")
        client = Garmin()

        # The Garmin client should automatically use garth.client
        client.garth = garth.client

        print("✅ Garmin client created and configured!")
        return client
        
    except Exception as e:
        error_msg = str(e)
        error_type = type(e).__name__

        # Provide helpful error messages based on error type
        if "401" in error_msg or "unauthorized" in error_msg.lower():
            helpful_msg = "Authentication failed - your OAuth tokens may have expired. You'll need to generate new tokens from Garmin Connect."
        elif "403" in error_msg or "forbidden" in error_msg.lower():
            helpful_msg = "Access forbidden - check that your OAuth1 tokens are correct."
        elif "token" in error_msg.lower() and "expired" in error_msg.lower():
            helpful_msg = "Your OAuth tokens have expired. Please generate new tokens from Garmin Connect."
        else:
            helpful_msg = f"Failed to authenticate with Garmin: {error_msg}"

        print(f"ERROR during token setup: {error_type}: {error_msg}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=helpful_msg
        )

@app.get("/", response_class=HTMLResponse)
def read_root():
    """Serve the beautiful web interface"""
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Garmin Workout Creator</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .container {
            background: white;
            border-radius: 20px;
            padding: 40px;
            max-width: 500px;
            width: 100%;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }
        h1 { color: #333; margin-bottom: 10px; font-size: 28px; }
        .subtitle { color: #666; margin-bottom: 30px; font-size: 14px; }
        .form-group { margin-bottom: 20px; }
        label {
            display: block;
            margin-bottom: 8px;
            color: #333;
            font-weight: 600;
            font-size: 14px;
        }
        textarea {
            width: 100%;
            padding: 12px 15px;
            border: 2px solid #e0e0e0;
            border-radius: 10px;
            font-size: 16px;
            transition: border-color 0.3s;
            font-family: inherit;
            resize: vertical;
            min-height: 100px;
        }
        textarea:focus {
            outline: none;
            border-color: #667eea;
        }
        .btn {
            width: 100%;
            padding: 15px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 10px;
            font-size: 18px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 20px rgba(102, 126, 234, 0.4);
        }
        .btn:active { transform: translateY(0); }
        .btn:disabled {
            background: #ccc;
            cursor: not-allowed;
            transform: none;
        }
        .examples {
            margin-top: 20px;
            padding: 15px;
            background: #f5f5f5;
            border-radius: 10px;
            font-size: 13px;
        }
        .examples h3 {
            margin-bottom: 10px;
            color: #333;
            font-size: 14px;
        }
        .examples p {
            margin: 5px 0;
            color: #666;
            cursor: pointer;
            padding: 5px;
            border-radius: 5px;
            transition: background 0.2s;
        }
        .examples p:hover { background: #e0e0e0; }
        .result {
            margin-top: 20px;
            padding: 15px;
            border-radius: 10px;
            display: none;
            animation: slideIn 0.3s ease;
        }
        @keyframes slideIn {
            from {
                opacity: 0;
                transform: translateY(-10px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
        .result.success {
            background: #d4edda;
            border: 2px solid #28a745;
            color: #155724;
            display: block;
        }
        .result.error {
            background: #f8d7da;
            border: 2px solid #dc3545;
            color: #721c24;
            display: block;
        }
        .result h3 { margin-bottom: 5px; font-size: 16px; }
        .loader {
            display: none;
            text-align: center;
            margin-top: 15px;
        }
        .loader.active { display: block; }
        .spinner {
            border: 3px solid #f3f3f3;
            border-top: 3px solid #667eea;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
            margin: 0 auto;
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🏃‍♂️ Garmin Workout Creator</h1>
        <p class="subtitle">Create workouts in natural language - No login needed!</p>
        
        <form id="workoutForm">
            <div class="form-group">
                <label for="workout">Workout Description</label>
                <textarea 
                    id="workout" 
                    placeholder="e.g., 10 min warmup, 5x(800m, 400m easy), 10 min cooldown"
                    required
                ></textarea>
            </div>
            
            <button type="submit" class="btn" id="submitBtn">
                Create Workout
            </button>
        </form>
        
        <div class="loader" id="loader">
            <div class="spinner"></div>
            <p style="margin-top: 10px; color: #666;">Creating workout...</p>
        </div>
        
        <div class="result" id="result"></div>
        
        <div class="examples">
            <h3>📝 Example Workouts (click to use):</h3>
            <p onclick="fillExample('5 min easy')">5 min easy</p>
            <p onclick="fillExample('10 min warmup, 20 min tempo, 5 min cooldown')">10 min warmup, 20 min tempo, 5 min cooldown</p>
            <p onclick="fillExample('10 min warmup, 5x(800m, 400m easy), 10 min cooldown')">10 min warmup, 5x(800m, 400m easy), 10 min cooldown</p>
            <p onclick="fillExample('3 miles easy')">3 miles easy</p>
        </div>
    </div>
    
    <script>
        const API_URL = window.location.origin + '/create-workout';
        
        function fillExample(text) {
            document.getElementById('workout').value = text;
        }
        
        document.getElementById('workoutForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const workout = document.getElementById('workout').value;
            
            // Show loader
            document.getElementById('loader').classList.add('active');
            document.getElementById('submitBtn').disabled = true;
            document.getElementById('result').style.display = 'none';
            
            try {
                const response = await fetch(API_URL, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        workout_text: workout
                    })
                });
                
                const data = await response.json();
                
                // Hide loader
                document.getElementById('loader').classList.remove('active');
                document.getElementById('submitBtn').disabled = false;
                
                if (response.ok && data.success) {
                    // Success
                    document.getElementById('result').className = 'result success';
                    document.getElementById('result').innerHTML = `
                        <h3>✅ Success!</h3>
                        <p><strong>${data.workout_name}</strong> has been created in Garmin Connect!</p>
                        <p style="margin-top: 10px; font-size: 12px;">Check the Garmin Connect app → Training → Workouts</p>
                    `;
                    
                    // Clear workout field
                    document.getElementById('workout').value = '';
                } else {
                    // Error from API
                    document.getElementById('result').className = 'result error';
                    document.getElementById('result').innerHTML = `
                        <h3>❌ Error</h3>
                        <p>${data.detail || data.message || 'Failed to create workout'}</p>
                    `;
                }
            } catch (error) {
                // Network error
                document.getElementById('loader').classList.remove('active');
                document.getElementById('submitBtn').disabled = false;
                document.getElementById('result').className = 'result error';
                document.getElementById('result').innerHTML = `
                    <h3>❌ Connection Error</h3>
                    <p>Could not connect to the API. Make sure the server is running.</p>
                    <p style="margin-top: 10px; font-size: 12px;">${error.message}</p>
                `;
            }
        });
    </script>
</body>
</html>
    """

@app.get("/health")
def health_check():
    return {"status": "healthy"}

@app.get("/help-tokens", response_class=HTMLResponse)
def help_tokens():
    """Guide for getting tokens with 2FA enabled"""
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Get Garmin Tokens (2FA Enabled)</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            background: white;
            border-radius: 20px;
            padding: 40px;
            max-width: 800px;
            margin: 0 auto;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }
        h1 { color: #333; margin-bottom: 20px; }
        h2 { color: #667eea; margin-top: 30px; margin-bottom: 15px; font-size: 20px; }
        .alert { background: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; margin: 20px 0; border-radius: 5px; }
        .step { background: #f8f9fa; padding: 20px; margin: 15px 0; border-radius: 10px; border-left: 4px solid #667eea; }
        .step-number { background: #667eea; color: white; border-radius: 50%; width: 30px; height: 30px; display: inline-flex; align-items: center; justify-content: center; font-weight: bold; margin-right: 10px; }
        code { background: #f5f5f5; padding: 2px 6px; border-radius: 3px; font-family: monospace; font-size: 14px; }
        .code-block { background: #2d2d2d; color: #f8f8f2; padding: 15px; border-radius: 8px; overflow-x: auto; margin: 10px 0; }
        .success { background: #d4edda; border-left: 4px solid #28a745; padding: 15px; margin: 20px 0; border-radius: 5px; }
        a { color: #667eea; text-decoration: none; }
        a:hover { text-decoration: underline; }
        .btn { display: inline-block; background: #667eea; color: white; padding: 10px 20px; border-radius: 8px; margin: 10px 5px; text-decoration: none; }
        .btn:hover { background: #5568d3; text-decoration: none; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔐 Getting Tokens with 2FA Enabled</h1>

        <div class="alert">
            <strong>⚠️ Note:</strong> Garmin doesn't allow disabling 2FA once enabled. This guide shows you how to get tokens anyway!
        </div>

        <h2>🎯 Best Method: Use a Desktop Computer</h2>

        <div class="step">
            <span class="step-number">1</span>
            <strong>Download the notebook</strong><br>
            Go to GitHub and download <code>Get_Garmin_Tokens.ipynb</code>
        </div>

        <div class="step">
            <span class="step-number">2</span>
            <strong>Open Google Colab</strong><br>
            Visit <a href="https://colab.research.google.com/" target="_blank">colab.research.google.com</a> and upload the notebook
        </div>

        <div class="step">
            <span class="step-number">3</span>
            <strong>Run in Colab</strong><br>
            Unfortunately, the standard login won't work with 2FA. <strong>But there's a workaround!</strong>
        </div>

        <h2>💡 Workaround for 2FA: Manual Token Extraction</h2>

        <div class="step">
            <span class="step-number">1</span>
            <strong>Open Chrome/Edge Developer Tools</strong><br>
            1. Go to <a href="https://connect.garmin.com/" target="_blank">connect.garmin.com</a><br>
            2. Log in (complete 2FA normally)<br>
            3. Press <code>F12</code> to open Developer Tools
        </div>

        <div class="step">
            <span class="step-number">2</span>
            <strong>Open Console Tab</strong><br>
            Click the <strong>Console</strong> tab in Developer Tools
        </div>

        <div class="step">
            <span class="step-number">3</span>
            <strong>Run This Script</strong><br>
            Paste this into the console and press Enter:
            <div class="code-block">// Get tokens from Garmin Connect session
try {
    // Try to find tokens in localStorage
    const storage = localStorage;
    const tokens = {};

    for (let i = 0; i < storage.length; i++) {
        const key = storage.key(i);
        if (key.includes('token') || key.includes('oauth') || key.includes('auth')) {
            console.log(key + ': ' + storage.getItem(key));
        }
    }

    console.log('\\n📋 Look for values containing: access_token, refresh_token, oauth_token, oauth_token_secret');
    console.log('⚠️  If you don\\'t see tokens, you\\'ll need to use Python on a desktop');
} catch(e) {
    console.error('Error:', e);
}</div>
        </div>

        <div class="step">
            <span class="step-number">4</span>
            <strong>Copy the Token Values</strong><br>
            Look for these 4 tokens in the console output and copy their values
        </div>

        <h2>🚨 Important: If Manual Extraction Doesn't Work</h2>

        <div class="alert">
            <strong>Alternative Solution:</strong> You'll need access to a desktop computer with Python installed. Here's why:<br><br>

            • The <code>garth</code> library needs to perform interactive login with 2FA<br>
            • This requires a Python environment (can't run in browser)<br>
            • Google Colab has limitations with interactive 2FA flows<br><br>

            <strong>Options:</strong><br>
            1. Use a desktop computer (yours or a friend's) to run <code>get_tokens.py</code><br>
            2. Use a cloud VM (AWS, Azure, etc.) with Python installed<br>
            3. Ask a developer friend to help run the script for you
        </div>

        <h2>✅ Once You Have Tokens</h2>

        <div class="success">
            <strong>Update Railway Variables:</strong><br>
            1. Go to Railway Dashboard → Your Service → Variables<br>
            2. Update these 4 variables:<br>
            &nbsp;&nbsp;&nbsp;• <code>GARMIN_OAUTH_ACCESS_TOKEN</code><br>
            &nbsp;&nbsp;&nbsp;• <code>GARMIN_OAUTH_REFRESH_TOKEN</code><br>
            &nbsp;&nbsp;&nbsp;• <code>GARMIN_OAUTH1_TOKEN</code><br>
            &nbsp;&nbsp;&nbsp;• <code>GARMIN_OAUTH1_TOKEN_SECRET</code><br>
            3. Railway will auto-deploy (1-2 min)<br>
            4. Test by creating a workout!
        </div>

        <div style="text-align: center; margin-top: 40px;">
            <a href="/" class="btn">← Back to Workout Creator</a>
            <a href="https://github.com/p6xt4ftwcv-svg/GarminWorkout" class="btn" target="_blank">View on GitHub</a>
        </div>
    </div>
</body>
</html>
    """

@app.get("/test-auth")
def test_auth():
    """Test if Garmin OAuth tokens are configured and valid"""
    try:
        print("Testing authentication...")
        client = authenticate_garmin()

        # Try to fetch workouts to verify authentication works
        print("Fetching workouts to test authentication...")
        try:
            # Use the garminconnect library's method to fetch workouts
            workouts = client.get_workouts()
            workout_count = len(workouts) if workouts else 0
            print(f"Successfully authenticated! Found {workout_count} workouts in account")

            return {
                "success": True,
                "message": "Authentication successful! Your tokens are working.",
                "tokens_configured": True,
                "workout_count": workout_count
            }
        except Exception as api_error:
            print(f"API call failed: {api_error}")
            return {
                "success": False,
                "message": f"Tokens configured but API call failed: {str(api_error)}",
                "tokens_configured": True,
                "api_error": str(api_error)
            }

    except HTTPException as e:
        # Token configuration error
        return {
            "success": False,
            "message": e.detail,
            "tokens_configured": False
        }
    except Exception as e:
        # Other errors
        print(f"Unexpected error: {e}")
        import traceback
        print(traceback.format_exc())
        return {
            "success": False,
            "message": f"Unexpected error: {str(e)}",
            "error_type": type(e).__name__
        }

@app.get("/debug-workout")
def debug_workout():
    """Fetch an existing workout to see the correct format"""
    try:
        print("Fetching existing workout for debugging...")
        client = authenticate_garmin()

        workouts = client.get_workouts()

        if not workouts or len(workouts) == 0:
            return {
                "success": False,
                "message": "No workouts found in your account. Create one manually in Garmin Connect first.",
                "workout_count": 0
            }

        # Get the first workout details
        first_workout = workouts[0]
        workout_id = first_workout.get('workoutId')

        print(f"Fetching details for workout ID: {workout_id}")

        # Try to get full workout details - garth returns JSON directly
        response = client.garth.get(
            "connectapi",
            f"/workout-service/workout/{workout_id}",
            api=True
        )

        # The response from garth.get() is already parsed JSON (dict)
        workout_details = response if isinstance(response, dict) else response.json() if hasattr(response, 'json') else {}

        # Print to logs instead of returning (to avoid serialization issues)
        print("="*80)
        print("WORKOUT DETAILS (check Railway logs):")
        print("="*80)
        print(json.dumps(workout_details, indent=2))
        print("="*80)

        return {
            "success": True,
            "message": "Workout details printed to Railway logs. Check the logs to see the format!",
            "workout_id": workout_id,
            "workout_name": first_workout.get('workoutName', 'Unknown')
        }

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        print(traceback.format_exc())
        return {
            "success": False,
            "message": str(e),
            "error_type": type(e).__name__
        }

@app.post("/create-workout")
async def create_workout(request: WorkoutRequest):
    """
    Create a Garmin workout from natural language text using OAuth tokens
    
    Example workout_text:
    - "10 min warmup, 5x(800m @ 5k pace, 400m easy), 10 min cooldown"
    - "15 minutes easy, 20 minutes tempo, 10 minutes cooldown"
    - "3 miles easy"
    """
    
    try:
        print("Starting workout creation...")
        print(f"Workout text: {request.workout_text}")
        
        # Authenticate using OAuth tokens from environment
        print("Authenticating with Garmin...")
        client = authenticate_garmin()
        print("Authentication successful!")
        
        # Parse the workout text
        print("Parsing workout...")
        parser = WorkoutParser()
        workout_json = parser.parse(request.workout_text, custom_name=request.workout_name)
        print(f"Parsed workout: {workout_json}")
        
        # Create workout in Garmin Connect using the high-level API
        print("Sending to Garmin...")
        print(f"Workout JSON: {json.dumps(workout_json, indent=2)}")
        
        # Use the garminconnect library's method to add workout
        response = client.garth.post(
            "connectapi",
            "/workout-service/workout",
            api=True,
            json=workout_json
        )
        
        print(f"Garmin response: {response}")
        
        # Now try to fetch workouts to verify
        print("Fetching workouts to verify...")
        try:
            workouts = client.get_workouts()
            print(f"Found {len(workouts)} workouts in account")
            if workouts:
                for w in workouts[:3]:
                    print(f"  - {w.get('workoutName', 'Unknown')}")
        except Exception as e:
            print(f"Could not fetch workouts: {e}")
        
        return {
            "success": True,
            "message": "Workout created successfully!",
            "workout_name": workout_json["workoutName"],
            "parsed_workout": workout_json,
            "garmin_response": response
        }
        
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {str(e)}")
        import traceback
        print(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
