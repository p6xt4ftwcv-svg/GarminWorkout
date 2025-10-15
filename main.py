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
            'warmup': 'WARMUP',
            'warm up': 'WARMUP',
            'cooldown': 'COOLDOWN',
            'cool down': 'COOLDOWN',
            'easy': 'ACTIVE',
            'recovery': 'RECOVERY',
            'interval': 'ACTIVE',
            'tempo': 'ACTIVE',
            'threshold': 'ACTIVE',
        }
    
    def parse(self, text: str) -> dict:
        """Parse workout text into Garmin workout JSON"""
        
        # Extract workout name if provided
        workout_name = f"Run Workout {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        
        # Create minimal workout structure - only required fields
        workout = {
            "workoutName": workout_name,
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
        
        # Split by common separators
        parts = re.split(r'[,;]|\bthen\b', text)
        
        for part in parts:
            part = part.strip()
            if not part:
                continue
            
            # Check for repeats: "5x(800m @ 5k pace, 400m easy)"
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
        
        # Determine intensity
        intensity = 'ACTIVE'
        for key, value in self.intensity_map.items():
            if key in text:
                intensity = value
                break
        
        # Parse duration - time based
        time_match = re.search(r'(\d+(?:\.\d+)?)\s*(min|minute|minutes|mins?)', text)
        if time_match:
            minutes = float(time_match.group(1))
            return {
                'type': 'step',
                'intensity': intensity,
                'duration_type': 'TIME',
                'duration_value': int(minutes * 60),  # Convert to seconds
                'target_type': 'NO_TARGET'
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
                'intensity': intensity,
                'duration_type': 'DISTANCE',
                'duration_value': int(meters * 100),  # Garmin uses centimeters
                'target_type': 'NO_TARGET'
            }
        
        # Default: 5 minutes if we can't parse
        return {
            'type': 'step',
            'intensity': intensity,
            'duration_type': 'TIME',
            'duration_value': 300,
            'target_type': 'NO_TARGET'
        }
    
    def _create_step(self, order: int, step_data: dict) -> dict:
        """Create Garmin workout step JSON"""
        
        if step_data['type'] == 'repeat':
            # Create a repeat step
            repeat_step = {
                "type": "WorkoutRepeatStep",
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
            # Create a minimal regular step - only required fields
            step = {
                "type": "WorkoutStep",
                "stepOrder": order,
                "intensity": step_data['intensity'],
                "durationType": step_data['duration_type'],
                "durationValue": step_data['duration_value'],
                "targetType": step_data['target_type']
            }
            
            # Add preferred unit
            if step_data['duration_type'] == 'TIME':
                step['preferredDurationUnit'] = 'SECOND'
            elif step_data['duration_type'] == 'DISTANCE':
                step['preferredDurationUnit'] = 'CENTIMETER'
            
            return step

def authenticate_garmin():
    """Authenticate with Garmin using OAuth tokens from environment variables"""
    print("Starting authentication...")
    
    # OAuth2 tokens
    access_token = os.getenv("GARMIN_OAUTH_ACCESS_TOKEN")
    refresh_token = os.getenv("GARMIN_OAUTH_REFRESH_TOKEN")
    
    # OAuth1 tokens (needed for API calls)
    oauth1_token = os.getenv("GARMIN_OAUTH1_TOKEN")
    oauth1_token_secret = os.getenv("GARMIN_OAUTH1_TOKEN_SECRET")
    
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
        print("Creating Garmin client...")
        
        # Configure garth with tokens first
        from garth.auth_tokens import OAuth2Token, OAuth1Token
        
        oauth2_dict = {
            'access_token': access_token,
            'refresh_token': refresh_token,
            'token_type': 'Bearer',
            'expires_in': 3600,
            'expires_at': int(time.time()) + 3600,
            'refresh_token_expires_in': 2592000,
            'refresh_token_expires_at': int(time.time()) + 2592000,
            'scope': '',
            'jti': '',
            'expired': False,
            'refresh_expired': False
        }
        
        oauth2_token = OAuth2Token(**oauth2_dict)
        garth.client.oauth2_token = oauth2_token
        print("✅ OAuth2 token set on garth")
        
        oauth1_token_obj = OAuth1Token(
            oauth_token=oauth1_token,
            oauth_token_secret=oauth1_token_secret
        )
        garth.client.oauth1_token = oauth1_token_obj
        print("✅ OAuth1 token set on garth")
        
        if not garth.client.domain:
            garth.client.domain = "garmin.com"
        
        garth.client.configure()
        print("✅ Garth configured")
        
        # Now create Garmin client and give it our configured garth
        client = Garmin(garth=garth.client)
        
        print("✅ Garmin client created!")
        return client
        
    except Exception as e:
        error_msg = f"Failed to authenticate with Garmin: {str(e)}"
        print(f"ERROR during token setup: {error_msg}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=error_msg
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
        workout_json = parser.parse(request.workout_text)
        print(f"Parsed workout: {workout_json}")
        
        # Override name if provided
        if request.workout_name:
            workout_json["workoutName"] = request.workout_name
        
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
