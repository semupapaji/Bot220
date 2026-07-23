from flask import Flask, request, jsonify
import asyncio
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from google.protobuf.json_format import MessageToJson
import binascii
import aiohttp
import requests
import json
import like_pb2
import like_count_pb2
import uid_generator_pb2
from google.protobuf.message import DecodeError
import os

app = Flask(__name__)

# =============================================================================
#  TOKEN LOADING FUNCTIONS
# =============================================================================

def load_tokens(server_name, token_type="like"):
    """
    Load tokens based on server and type.
    token_type: "like" or "visit"
    """
    try:
        if token_type == "like":
            if server_name == "IND":
                filename = "token_ind.json"
            elif server_name in {"BR", "US", "SAC", "NA"}:
                filename = "token_br.json"
            else:
                filename = "token_bd.json"
        else:  # visit tokens
            if server_name == "IND":
                filename = "token_ind_visit.json"
            elif server_name in {"BR", "US", "SAC", "NA"}:
                filename = "token_br_visit.json"
            else:
                filename = "token_bd_visit.json"
        
        if not os.path.exists(filename):
            app.logger.error(f"File not found: {filename}")
            return None
            
        with open(filename, "r") as f:
            tokens = json.load(f)
            
        if not tokens or len(tokens) == 0:
            app.logger.error(f"Empty or invalid tokens in {filename}")
            return None
            
        return tokens
    except json.JSONDecodeError as e:
        app.logger.error(f"JSON decode error in {filename}: {e}")
        return None
    except Exception as e:
        app.logger.error(f"Error loading tokens for server {server_name} ({token_type}): {e}")
        return None

def validate_tokens(server_name):
    """
    Validate both like and visit tokens exist and are valid.
    Returns (bool, str) - (success, error_message)
    """
    # Check like tokens
    like_tokens = load_tokens(server_name, "like")
    if like_tokens is None:
        return False, f"Like tokens missing or invalid for server {server_name}"
    
    # Check visit tokens
    visit_tokens = load_tokens(server_name, "visit")
    if visit_tokens is None:
        return False, f"Visit tokens missing or invalid for server {server_name}"
    
    # Check if tokens have required fields
    try:
        if not like_tokens[0].get('token'):
            return False, f"Invalid like token format for server {server_name}"
        if not visit_tokens[0].get('token'):
            return False, f"Invalid visit token format for server {server_name}"
    except (IndexError, AttributeError):
        return False, f"Token format error for server {server_name}"
    
    return True, "OK"

# =============================================================================
#  ENCRYPTION & PROTOBUF FUNCTIONS
# =============================================================================

def encrypt_message(plaintext):
    try:
        key = b'Yg&tc%DEuh6%Zc^8'
        iv = b'6oyZDr22E3ychjM%'
        cipher = AES.new(key, AES.MODE_CBC, iv)
        padded_message = pad(plaintext, AES.block_size)
        encrypted_message = cipher.encrypt(padded_message)
        return binascii.hexlify(encrypted_message).decode('utf-8')
    except Exception as e:
        app.logger.error(f"Error encrypting message: {e}")
        return None

def create_protobuf_message(user_id, region):
    try:
        message = like_pb2.like()
        message.uid = int(user_id)
        message.region = region
        return message.SerializeToString()
    except Exception as e:
        app.logger.error(f"Error creating protobuf message: {e}")
        return None

def create_protobuf(uid):
    try:
        message = uid_generator_pb2.uid_generator()
        message.saturn_ = int(uid)
        message.garena = 1
        return message.SerializeToString()
    except Exception as e:
        app.logger.error(f"Error creating uid protobuf: {e}")
        return None

def enc(uid):
    protobuf_data = create_protobuf(uid)
    if protobuf_data is None:
        return None
    encrypted_uid = encrypt_message(protobuf_data)
    return encrypted_uid

def decode_protobuf(binary):
    try:
        items = like_count_pb2.Info()
        items.ParseFromString(binary)
        return items
    except DecodeError as e:
        app.logger.error(f"Error decoding Protobuf data: {e}")
        return None
    except Exception as e:
        app.logger.error(f"Unexpected error during protobuf decoding: {e}")
        return None

# =============================================================================
#  REQUEST FUNCTIONS
# =============================================================================

async def send_request(encrypted_uid, token, url):
    try:
        edata = bytes.fromhex(encrypted_uid)
        headers = {
            'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
            'Connection': "Keep-Alive",
            'Accept-Encoding': "gzip",
            'Authorization': f"Bearer {token}",
            'Content-Type': "application/x-www-form-urlencoded",
            'Expect': "100-continue",
            'X-Unity-Version': "2018.4.11f1",
            'X-GA': "v1 1",
            'ReleaseVersion': "OB54"
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=edata, headers=headers) as response:
                if response.status != 200:
                    app.logger.error(f"Request failed with status code: {response.status}")
                    return response.status
                return await response.text()
    except Exception as e:
        app.logger.error(f"Exception in send_request: {e}")
        return None

async def send_multiple_requests(uid, server_name, url):
    try:
        region = server_name
        protobuf_message = create_protobuf_message(uid, region)
        if protobuf_message is None:
            app.logger.error("Failed to create protobuf message.")
            return None
        encrypted_uid = encrypt_message(protobuf_message)
        if encrypted_uid is None:
            app.logger.error("Encryption failed.")
            return None
        
        # Load like tokens
        tokens = load_tokens(server_name, "like")
        if tokens is None:
            app.logger.error("Failed to load like tokens.")
            return None
            
        tasks = []
        for i in range(500):
            token = tokens[i % len(tokens)]["token"]
            tasks.append(send_request(encrypted_uid, token, url))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return results
    except Exception as e:
        app.logger.error(f"Exception in send_multiple_requests: {e}")
        return None

def make_request(encrypt, server_name, token):
    try:
        if server_name == "IND":
            url = "https://client.ind.freefiremobile.com/GetPlayerPersonalShow"
        elif server_name in {"BR", "US", "SAC", "NA"}:
            url = "https://client.us.freefiremobile.com/GetPlayerPersonalShow"
        else:
            url = "https://clientbp.ggpolarbear.com/GetPlayerPersonalShow"
        edata = bytes.fromhex(encrypt)
        headers = {
            'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
            'Connection': "Keep-Alive",
            'Accept-Encoding': "gzip",
            'Authorization': f"Bearer {token}",
            'Content-Type': "application/x-www-form-urlencoded",
            'Expect': "100-continue",
            'X-Unity-Version': "2018.4.11f1",
            'X-GA': "v1 1",
            'ReleaseVersion': "OB54"
        }
        response = requests.post(url, data=edata, headers=headers, verify=False)
        hex_data = response.content.hex()
        binary = bytes.fromhex(hex_data)
        decode = decode_protobuf(binary)
        if decode is None:
            app.logger.error("Protobuf decoding returned None.")
        return decode
    except Exception as e:
        app.logger.error(f"Error in make_request: {e}")
        return None

# =============================================================================
#  MAIN API ROUTE
# =============================================================================

@app.route('/like', methods=['GET'])
def handle_requests():
    uid = request.args.get("uid")
    server_name = request.args.get("server_name", "").upper()
    
    if not uid or not server_name:
        return jsonify({"error": "UID and server_name are required"}), 400

    try:
        # ===== STEP 1: VALIDATE BOTH TOKEN FILES =====
        valid, error_msg = validate_tokens(server_name)
        if not valid:
            app.logger.error(f"Token validation failed: {error_msg}")
            return jsonify({
                "error": error_msg,
                "status": 0,
                "message": "Token validation failed. Please check token files."
            }), 400

        def process_request():
            # Load visit token for profile viewing
            visit_tokens = load_tokens(server_name, "visit")
            if visit_tokens is None:
                raise Exception(f"Failed to load visit tokens for {server_name}")
            
            visit_token = visit_tokens[0]['token']
            
            # Load like token for like operations
            like_tokens = load_tokens(server_name, "like")
            if like_tokens is None:
                raise Exception(f"Failed to load like tokens for {server_name}")
            
            like_token = like_tokens[0]['token']
            
            # Encrypt UID
            encrypted_uid = enc(uid)
            if encrypted_uid is None:
                raise Exception("Encryption of UID failed.")

            # ===== GET PROFILE BEFORE LIKES (USING VISIT TOKEN) =====
            before = make_request(encrypted_uid, server_name, visit_token)
            if before is None:
                raise Exception("Failed to retrieve initial player info with visit token.")
            
            try:
                jsone = MessageToJson(before)
            except Exception as e:
                raise Exception(f"Error converting 'before' protobuf to JSON: {e}")
            
            data_before = json.loads(jsone)
            before_like = data_before.get('AccountInfo', {}).get('Likes', 0)
            try:
                before_like = int(before_like)
            except Exception:
                before_like = 0
            app.logger.info(f"Likes before command: {before_like}")

            # ===== SEND LIKE REQUESTS (USING LIKE TOKENS) =====
            if server_name == "IND":
                url = "https://client.ind.freefiremobile.com/LikeProfile"
            elif server_name in {"BR", "US", "SAC", "NA"}:
                url = "https://client.us.freefiremobile.com/LikeProfile"
            else:
                url = "https://clientbp.ggpolarbear.com/LikeProfile"

            asyncio.run(send_multiple_requests(uid, server_name, url))

            # ===== GET PROFILE AFTER LIKES (USING VISIT TOKEN) =====
            after = make_request(encrypted_uid, server_name, visit_token)
            if after is None:
                raise Exception("Failed to retrieve player info after like requests.")
            
            try:
                jsone_after = MessageToJson(after)
            except Exception as e:
                raise Exception(f"Error converting 'after' protobuf to JSON: {e}")
            
            data_after = json.loads(jsone_after)
            after_like = int(data_after.get('AccountInfo', {}).get('Likes', 0))
            player_uid = int(data_after.get('AccountInfo', {}).get('UID', 0))
            player_name = str(data_after.get('AccountInfo', {}).get('PlayerNickname', ''))
            like_given = after_like - before_like
            status = 1 if like_given != 0 else 2
            
            result = {
                "LikesGivenByAPI": like_given,
                "LikesafterCommand": after_like,
                "LikesbeforeCommand": before_like,
                "PlayerNickname": player_name,
                "UID": player_uid,
                "status": status,
                "OB54": "Active",
                "TokenStatus": {
                    "VisitToken": "Valid",
                    "LikeToken": "Valid"
                }
            }
            return result

        result = process_request()
        return jsonify(result)
        
    except Exception as e:
        app.logger.error(f"Error processing request: {e}")
        return jsonify({
            "error": str(e),
            "status": 0,
            "message": "Internal server error"
        }), 500

# =============================================================================
#  HEALTH CHECK ENDPOINT
# =============================================================================

@app.route('/health', methods=['GET'])
def health_check():
    """Check if all token files are present and valid"""
    servers = ["IND", "BR", "US", "SAC", "NA", "BD"]
    status = {}
    all_valid = True
    
    for server in servers:
        like_valid = load_tokens(server, "like") is not None
        visit_valid = load_tokens(server, "visit") is not None
        status[server] = {
            "like_tokens": "Valid" if like_valid else "Missing/Invalid",
            "visit_tokens": "Valid" if visit_valid else "Missing/Invalid"
        }
        if not like_valid or not visit_valid:
            all_valid = False
    
    return jsonify({
        "status": "OK" if all_valid else "WARNING",
        "message": "All token files validated" if all_valid else "Some token files are missing or invalid",
        "details": status
    })

if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)
