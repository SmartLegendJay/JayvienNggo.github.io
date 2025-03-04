from http.server import SimpleHTTPRequestHandler, HTTPServer
import subprocess
import json
import logging
import threading

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class GoHandler(SimpleHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/evaluate':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length).decode('utf-8')
            try:
                data = json.loads(post_data)
                board_state = data.get('board_state')
                if board_state is None:
                    self.send_error(400, "Invalid request: board_state missing")
                    return

                # Use threading to prevent blocking
                thread = threading.Thread(target=self.run_ai_engine, args=(board_state,))
                thread.start()
                self.send_response(202)  # Accepted
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "AI engine processing"}).encode('utf-8'))

            except json.JSONDecodeError:
                self.send_error(400, "Invalid JSON")
            except Exception as e:
                logging.error(f"Error processing request: {e}", exc_info=True)
                self.send_error(500, "Internal Server Error")
        else:
            super().do_POST()

    def run_ai_engine(self, board_state):
        try:
            process = subprocess.Popen(
                ['python', 'ai_engine.py', json.dumps(board_state)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            stdout, stderr = process.communicate()
            if process.returncode == 0:
                logging.info(f"AI engine successful. output: {stdout}")
                #Handle the stdout here. Perhaps save it to a file or database.
                #For example:
                #with open("ai_results.txt", "a") as f:
                #    f.write(stdout + "\n")
            else:
                logging.error(f"Error in AI engine: {stderr}")

        except FileNotFoundError:
            logging.error("AI engine script not found")
        except Exception as e:
            logging.error(f"Error executing AI engine: {e}", exc_info=True)

    def do_GET(self):
        if self.path == '/':
            self.path = '/index.html'
        return super().do_GET()

if __name__ == '__main__':
    port = 8000
    httpd = HTTPServer(('localhost', port), GoHandler)
    logging.info(f'Serving at http://localhost:{port}')
    httpd.serve_forever()