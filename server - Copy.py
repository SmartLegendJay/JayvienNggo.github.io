from flask import *
from flask_cors import CORS  # Enable CORS
import os,json,logging,subprocess,time
from threading import Thread
import sys
import logging
import requests

logging.basicConfig(level=logging.ERROR)

app = Flask(__name__)
app.config['DEBUG'] = True
CORS(app)  # Enable CORS for all routes
game_moves = []
moves = []
for i, move in enumerate(moves):
    color = "b" if i % 2 == 0 else "w"
    row = ord(move[0]) - ord('a')
    col = int(move[1:]) - 1
    vertex = f"{chr(ord('a') + col)}{row+1}"
    game_moves.append([color, vertex])
# Load user config (if exists)
config_path = "C:/Users/User/.katrain/config.json"
if os.path.exists(config_path):
    with open(config_path, "r") as file:
        user_config = json.load(file)
else:
    user_config = {}
print("Game moves:", game_moves)

# Default configuration
default_config = {
    "katago": "C:/baduk/lizzie/katago.exe",  # Path to KataGo executable
    "model": "C:/baduk/lizzie/KataGo18b9x9.gz",  # Model file
    "config": "C:/baduk/KaTrain/analysis_config.cfg",  # KataGo config file
    "numSearchThreads": 6,
    "maxVisits": 200,
   # "fast_visits": 50,
    "maxTime": 3.0,
    "analysisWideRootNoise": 0.01,
   # "_enable_ownership": True,
   # "allow_recovery": True,
   # "logAllGTPCommunication": False,
    "logSearchInfo": False,
    "homeDataDir": "C:/Users/User/.katrain",
    "logFile": "C:/Users/User/Desktop/analysis.log",
    "numAnalysisThreads": 6,
    "openclDeviceToUse": 0,
    "numAnalysisThreads": 4,
    "reportAnalysisWinratesAs": "BLACK"
}

katago_path = default_config["katago"]

# Merge user config (overwrites defaults if defined)
config = {**user_config, **default_config}


# Set up logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# KataGo Engine Wrapper
class KataGoEngine:
    def __init__(self, katago_path, config_path, model_path, additional_args=None):
            if additional_args is None:
                additional_args = []

            # Verify that the paths exist
            if not os.path.isfile(katago_path):
                raise FileNotFoundError(f"KataGo executable not found at {katago_path}")
            if not os.path.isfile(model_path):
                raise FileNotFoundError(f"KataGo model file not found at {model_path}")
            if not os.path.isfile(config_path):
                raise FileNotFoundError(f"KataGo config file not found at {config_path}")
            # Generate additional arguments based on config overrides
            override_args = []
            #for key, value in config.items():
            # For each item in the default config, add it to the override args
            override_config_str = ",".join([f"{key}={value}" for key, value in config.items()])

            # Start KataGo subprocess with dynamic config overrides
            self.katago = subprocess.Popen(
                [katago_path, "analysis", "-config", config_path, "-model", model_path, "-override-config", override_config_str] + additional_args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True  # Ensures output is treated as text instead of bytes
            )

            # Start KataGo subprocess
            #self.katago = subprocess.Popen(
            #    [katago_path, "analysis", "-config", config_path, "-model", model_path, "-override-config", "numAnalysisThreads=8"],
            #    stdin=subprocess.PIPE,
            #    stdout=subprocess.PIPE,
            #    stderr=subprocess.PIPE,
            #    text=True  # Ensures output is treated as text instead of bytes
           # )

            # Thread to log KataGo's stderr
            self.stderr_thread = Thread(target=self.log_stderr, daemon=True)
            self.stderr_thread.start()

    def log_stderr(self):
        while self.katago.poll() is None:
            error_output = self.katago.stderr.readline().strip()
            if error_output and not error_output.startswith("2025-"):
                logger.error(f"KataGo stderr: {error_output}")

        self.stderr_thread = Thread(target=self.log_stderr, daemon=True)
        self.stderr_thread.start()
    def send_move(self, move):
        """Send a move to KataGo and update the game state."""
        try:
        # Convert move format (e.g., "B D4" → ["b", "D4"])
            color, position = move.split()
            formatted_move = [color.lower(), position]

            # Store the move
            game_moves.append(formatted_move)

            logger.info(f"Move sent: {formatted_move}")

        except Exception as e:
            logger.error(f"Error in send_move(): {e}")

    def close(self):
        self.katago.stdin.close()
        self.katago.terminate()
        self.stderr_thread.join()

    def query_winrate(self, moves, board_size=9, komi=7.5, rules="Chinese"):
        query = {
            "id": "query1",
            "rules": rules,
            "komi": komi,
            "boardXSize": board_size,
            "boardYSize": board_size,
            "includePolicy": True,
            "includeOwnership": True,
            "moves": moves
        }
        self.katago.stdin.write(json.dumps(query) + "\n")
        self.katago.stdin.flush()

        response_lines = []
        while True:
            line = self.katago.stdout.readline()
            if not line:  # KataGo process likely terminated
                return {"error": "KataGo process terminated unexpectedly"}
            response_lines.append(line.strip())
            try:
                full_response = "".join(response_lines)
                response = json.loads(full_response)  # Attempt to parse
                logger.debug(f"Received response from KataGo: {response}")
                return response  # Success!
            except json.JSONDecodeError:
                # Incomplete JSON, continue reading
                pass
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                return {"error": str(e)}

        # Send query
        self.katago.stdin.write(json.dumps(query) + "\n")
        self.katago.stdin.flush()

        # Read the response
        response_line = self.katago.stdout.readline().strip()
        try:
            response = json.loads(response_line)
        except json.JSONDecodeError:
            logger.info(f"Failed to decode JSON response: {response_line}")
            return None

        # Check for error in response
        if "error" in response:
            logger.info(f"Error from KataGo: {response['error']}")
            return None

        # Return winrate if available
        if "winrate" in response:
            return response["winrate"]
        else:
            logger.info("No winrate data in response.")
            return None

# Initialize KataGo Engine
engine = None
def initialize_engine():
    global engine
    try:
        # Check if config.json file exists and delete it if needed
        config_file_path = "C:/Users/User/.katrain/config.json"
        if os.path.exists(config_file_path):
            os.remove(config_file_path)

        logger.info("Initializing KataGo engine...")
        engine = KataGoEngine(default_config["katago"], default_config["config"], default_config["model"])
        logger.info("KataGo engine initialized.")
    except Exception as e:
        logger.error(f"Error initializing KataGoEngine: {e}")
        engine = None

    if engine is None:
        logger.error("Failed to initialize KataGo engine. Exiting.")
        sys.exit(1)


# Flask Routes
@app.route('/')
def index():
    return send_from_directory(".", "TestWeb.html")
@app.route('/css/<path:path>')
def send_css(path):
    return send_from_directory('css', path)
print("Moves list (top-level):", moves)
@app.route('/play_move', methods=['POST'])
def play_move():
    print("------------ REQUEST RECEIVED ------------")
    data = request.get_json()
    print("Data:", data)
    move = data.get("move")
    print("Move:", move)

    # --- Player 1 (Black) Move ---
    if move:  # Only process if player has made a move
        move = move.replace("I", "T")  # Handle potential 'I' to 'T' conversion
        color, position = move.split()
        formatted_move = [color.lower(), position]
        moves.append(move)
        game_moves.append(formatted_move)
        print("Moves list:", moves)

    # --- AI Player 2 (White) Move ---
    ai_move = get_ai_move()  # Get AI's move
    if ai_move:
        moves.append(ai_move)
        color, position = ai_move.split()
        formatted_move = [color.lower(), position]
        game_moves.append(formatted_move)
        print("AI Move:", ai_move)
    else:
        print("AI returned no move")
        return jsonify({"success": False, "error": "AI returned no move"}), 500

    # Get the updated winrate (after both moves)
    winrate_response = requests.get('http://localhost:5000/get_winrate')
    if winrate_response.status_code == 200:
        winrate_data = winrate_response.json()
    else:
        print("Error getting winrate:", winrate_response.status_code)
        return jsonify({"success": False, "error": "Failed to get winrate"}), 500

    return jsonify({
        "success": True,
        "winrate": winrate_data,
        "ai_move": ai_move  # Return the AI move to the frontend
    })


def get_ai_move():
    """Gets KataGo's suggested move."""
    try:
        if not engine:
            logger.warning("Engine not initialized, attempting to initialize.")
            initialize_engine()

        if not engine:
            return None

        response = engine.query_winrate(game_moves)
        print("Game Moves sent to KataGo:", game_moves)  # Print for verification
        print("Full KataGo Response:", json.dumps(response, indent=4))
        logger.info(f"Game Moves sent to KataGo: {game_moves}") #Log the moves
        logger.info(f"Full KataGo Response: {json.dumps(response)}")

        if response is None:
            logger.error("KataGo returned None")
            return None

        if "error" in response:
            logger.error(f"KataGo returned an error: {response['error']}")
            return None

        if "rootInfo" not in response:
            logger.error(f"KataGo response missing 'rootInfo': {response}")
            return None

        if "bestMove" not in response["rootInfo"]:
            logger.error(f"KataGo response missing 'bestMove' in rootInfo: {response}")
            return None

        try:
            best_move = response["rootInfo"]["bestMove"]
            color = "W" if len(game_moves) % 2 != 0 else "B"
            ai_move = f"{color} {best_move}"
            return ai_move

        except KeyError:  # Handle missing 'bestMove'
            logger.error("KataGo response missing 'bestMove'. Full Response: %s", json.dumps(response, indent=4))
            return None  # Or handle differently (e.g., choose a random move)
        except TypeError: # Handle unexpected data types
            logger.error("KataGo response 'rootInfo' or 'bestMove' has unexpected type. Full Response: %s", json.dumps(response, indent=4))
            return None
        except Exception as e: # Catch any other exceptions
            logger.exception(f"Unexpected error in get_ai_move: {e}. Full Response: %s", json.dumps(response, indent=4))
            return None


    except Exception as e:
        logger.exception(f"Error in get_ai_move: {e}")
        return None
    
@app.route('/get_moves', methods=['GET'])
def get_moves():
    # Handle GET request
    return jsonify({"moves": moves})
winrate_data = {'black_winrate': 0.5, 'white_winrate': 0.5}

@app.route('/update_winrate', methods=['POST'])
def update_winrate():
    data = request.get_json()
    winrate_data['black_winrate'] = data['black_winrate']
    winrate_data['white_winrate'] = data['white_winrate']
    
    # Return the updated winrate
    return jsonify(winrate_data)

@app.route('/get_winrate', methods=['GET'])
def get_winrate():
    """Fetch winrate from KataGo based on current game state"""
    try:
        if not engine:
            logger.warning("Engine not initialized, attempting to initialize.")
            initialize_engine()
        
        if not engine:
            return "KataGo engine not initialized", 500

        if not game_moves:
            return "No moves played yet", 400

        # Query KataGo for winrate based on move history
        response = engine.query_winrate(game_moves)
        print("Game Moves sent to KataGo:", game_moves)  # Print for verification
        print("Full KataGo Response:", json.dumps(response, indent=4))
        logger.info(f"Game Moves sent to KataGo: {game_moves}") #Log the moves
        logger.info(f"Full KataGo Response: {json.dumps(response)}")

        if response is None:
            return jsonify({"error": "Failed to retrieve winrate"}), 500

        if "error" in response:
            return jsonify({"error": response["error"]}), 500

        if "rootInfo" not in response:
            return jsonify({"error": "No root info available"}), 500

        winrate = response["rootInfo"]["winrate"] if "rootInfo" in response else None
        winning_color = "Black" if winrate > 0.5 else "White"
        #winning_percentage = round(abs(winrate - 0.5) * 100, 2)
        black_winrate = round(winrate * 100, 2)
        white_winrate = round((1 - winrate) * 100, 2)

        return jsonify({
            "winning_color": winning_color,
            "black_winrate": black_winrate,
            "white_winrate": white_winrate
        })

    except Exception as e:
        logger.error(f"Error in /get_winrate: {e}")
        return jsonify({"error": str(e)}), 500
@app.route('/kyueasy')
def kyueasy():
    return send_from_directory('.', 'kyueasy.html')
@app.route('/kyumiddle')
def kyumiddle():
    return send_from_directory('.', 'kyumiddle.html')
@app.route('/kyuhard')
def kyuhard():
    return send_from_directory('.', 'kyuhard.html')
@app.route('/daneasy')
def daneasy():
    return send_from_directory('.', 'daneasy.html')
@app.route('/danmiddle')
def danmiddle():
    return send_from_directory('.', 'danmiddle.html')
@app.route('/danhard')
def danhard():
    return send_from_directory('.', 'danhard.html')
@app.route('/play1')
def play1():
    return send_from_directory('.', 'play1.html')
@app.route('/play2')
def play2():
    return send_from_directory('.', 'play2.html') 
@app.route('/play3')
def play3():
    return send_from_directory('.', 'play3.html')  
@app.route('/play4')
def play4():
    return send_from_directory('.', 'play4.html')         
@app.route('/reset_game', methods=['GET'])
def reset_game():
    global game_moves
    global moves
    game_moves = []
    moves = []
    return jsonify({"success": True})
# Run Flask app
if __name__ == '__main__':
    initialize_engine()
    app.run(debug=True)
