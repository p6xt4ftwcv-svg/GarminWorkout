from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import garth
import os
import re
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
    garmin_email: str
    garmin_password: str
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
        
        workout = {
            "workoutName": workout_name,
            "sportType": {"sportTypeId": 1},  # Running
            "workoutSegments": [{
                "segmentOrder": 1,
                "sportType": {"sportTypeId": 1},
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
                "workoutSteps": []
            }
            
            for idx, inner_step in enumerate(step_data['steps']):
                repeat_step["workoutSteps"].append(
                    self._create_step(idx + 1, inner_step)
                )
            
            return repeat_step
        
        else:
            # Create a regular step
            return {
                "type": "WorkoutStep",
                "stepOrder": order,
                "intensity": step_data['intensity'],
                "durationType": step_data['duration_type'],
                "durationValue": step_data['duration_value'],
                "targetType": step_data['target_type']
            }

@app.get("/")
def read_root():
    return {
        "message": "Garmin Workout API",
        "endpoints": {
            "/create-workout": "POST - Create a workout from text",
            "/health": "GET - Health check"
        }
    }

@app.get("/health")
def health_check():
    return {"status": "healthy"}

@app.post("/create-workout")
async def create_workout(request: WorkoutRequest):
    """
    Create a Garmin workout from natural language text
    
    Example workout_text:
    - "10 min warmup, 5x(800m @ 5k pace, 400m easy), 10 min cooldown"
    - "15 minutes easy, 20 minutes tempo, 10 minutes cooldown"
    - "3 miles easy"
    """
    
    try:
        # Login to Garmin
        garth.login(request.garmin_email, request.garmin_password)
        
        # Parse the workout text
        parser = WorkoutParser()
        workout_json = parser.parse(request.workout_text)
        
        # Override name if provided
        if request.workout_name:
            workout_json["workoutName"] = request.workout_name
        
        # Create workout in Garmin Connect
        response = garth.post(
            "workout-service/workout",
            api=True,
            json=workout_json
        )
        
        return {
            "success": True,
            "message": "Workout created successfully!",
            "workout_name": workout_json["workoutName"],
            "workout_id": response.get("workoutId"),
            "parsed_workout": workout_json
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
