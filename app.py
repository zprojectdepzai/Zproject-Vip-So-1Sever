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
import threading
import time
import os
import concurrent.futures

app = Flask(__name__)

GLOBAL_TOKENS = []
TOKEN_URL = "https://zproject-api-sever-tele.x10.mx/token_sg.json"
tokens_lock = threading.Lock()
initial_tokens_loaded = threading.Event()

def fetch_tokens_from_url():
    try:
        app.logger.info(f"Fetching tokens from: {TOKEN_URL}")
        response = requests.get(TOKEN_URL, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        app.logger.exception(f"Timeout when fetching tokens from URL {TOKEN_URL}")
        return None
    except requests.exceptions.RequestException as e:
        app.logger.exception(f"Error fetching tokens from URL {TOKEN_URL}: {e}")
        return None
    except json.JSONDecodeError:
        app.logger.exception(f"Failed to decode JSON from token URL {TOKEN_URL}. Response content: {response.text}")
        return None

def refresh_tokens():
    global GLOBAL_TOKENS
    app.logger.info("Attempting to refresh tokens...")
    new_tokens = fetch_tokens_from_url()
    if new_tokens:
        with tokens_lock:
            GLOBAL_TOKENS = new_tokens
        app.logger.info(f"Tokens refreshed successfully. Loaded {len(GLOBAL_TOKENS)} tokens.")
        initial_tokens_loaded.set()
    else:
        app.logger.warning("Failed to refresh tokens. Keeping existing tokens (if any).")
        if not GLOBAL_TOKENS:
            app.logger.error("No tokens loaded after initial attempt or refresh failure.")

def start_token_refresh_scheduler():
    def scheduler():
        refresh_tokens()
        while True:
            time.sleep(120)
            refresh_tokens()

    thread = threading.Thread(target=scheduler, daemon=True)
    thread.start()
    app.logger.info("Token refresh scheduler started.")
    
def get_available_tokens():
    with tokens_lock:
        return list(GLOBAL_TOKENS)

def encrypt_message(plaintext):
    try:
        key = b'Yg&tc%DEuh6%Zc^8'
        iv = b'6oyZDr22E3ychjM%'
        cipher = AES.new(key, AES.MODE_CBC, iv)
        padded_message = pad(plaintext, AES.block_size)
        encrypted_message = cipher.encrypt(padded_message)
        return binascii.hexlify(encrypted_message).decode('utf-8')
    except Exception as e:
        app.logger.exception(f"Error encrypting message: {e}")
        return None

def create_protobuf_message(user_id, region):
    try:
        message = like_pb2.like()
        message.uid = int(user_id)
        message.region = region
        return message.SerializeToString()
    except Exception as e:
        app.logger.exception(f"Error creating protobuf message: {e}")
        return None

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
            'ReleaseVersion': "OB49"
        }
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.post(url, data=edata, headers=headers) as response:
                if response.status != 200:
                    app.logger.warning(f"Request to {url} failed with status code: {response.status} for token starting with {token[:10]}...")
                    return response.status
                return await response.text()
    except aiohttp.ClientError as e:
        app.logger.exception(f"aiohttp ClientError in send_request to {url}: {e}")
        return None
    except Exception as e:
        app.logger.exception(f"Unexpected exception in send_request to {url}: {e}")
        return None

async def send_multiple_requests(uid, server_name, url):
    try:
        region = server_name
        protobuf_message = create_protobuf_message(uid, region)
        if protobuf_message is None:
            app.logger.error("Failed to create protobuf message for multiple requests.")
            return None
        encrypted_uid = encrypt_message(protobuf_message)
        if encrypted_uid is None:
            app.logger.error("Encryption failed for multiple requests.")
            return None
        
        tasks = []
        tokens = get_available_tokens()
        if not tokens:
            app.logger.error("No tokens available to send multiple requests.")
            return None
        
        concurrent_limit = 50 
        
        for i in range(100):
            token = tokens[i % len(tokens)]["token"]
            tasks.append(send_request(encrypted_uid, token, url))
       
        semaphore = asyncio.Semaphore(concurrent_limit)
        async def sem_task(task):
            async with semaphore:
                return await task
        
        results = await asyncio.gather(*[sem_task(task) for task in tasks], return_exceptions=True)
        
        return results
    except Exception as e:
        app.logger.exception(f"Exception in send_multiple_requests: {e}")
        return None

def create_protobuf(uid):
    try:
        message = uid_generator_pb2.uid_generator()
        message.saturn_ = int(uid)
        message.garena = 1
        return message.SerializeToString()
    except Exception as e:
        app.logger.exception(f"Error creating uid protobuf: {e}")
        return None

def enc(uid):
    protobuf_data = create_protobuf(uid)
    if protobuf_data is None:
        return None
    encrypted_uid = encrypt_message(protobuf_data)
    return encrypted_uid

async def make_async_request(encrypt, server_name, token):
    try:
        if server_name == "IND":
            url = "https://client.ind.freefiremobile.com/GetPlayerPersonalShow"
        elif server_name in {"BR", "US", "SAC", "NA"}:
            url = "https://client.us.freefiremobile.com/GetPlayerPersonalShow"
        else:
            url = "https://clientbp.ggblueshark.com/GetPlayerPersonalShow"

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
            'ReleaseVersion': "OB49"
        }

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.post(url, data=edata, headers=headers) as response:
                response.raise_for_status()
                hex_data = (await response.read()).hex()
                binary = bytes.fromhex(hex_data)
                decode = decode_protobuf(binary)
                if decode is None:
                    app.logger.error("Protobuf decoding returned None for GetPlayerPersonalShow.")
                return decode
    except aiohttp.ClientResponseError as e:
        app.logger.exception(f"HTTP Error in make_async_request (status {e.status}) to {url}: {e}")
        return None
    except aiohttp.ClientError as e:
        app.logger.exception(f"aiohttp ClientError in make_async_request to {url}: {e}")
        return None
    except Exception as e:
        app.logger.exception(f"Unexpected error in make_async_request to {url}: {e}")
        return None

def decode_protobuf(binary):
    try:
        items = like_count_pb2.Info()
        items.ParseFromString(binary)
        return items
    except DecodeError as e:
        app.logger.exception(f"Error decoding Protobuf data: {e}")
        return None
    except Exception as e:
        app.logger.exception(f"Unexpected error during protobuf decoding: {e}")
        return None

def run_async_in_thread(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

def process_request_sync_wrapper(uid, server_name):
    tokens = get_available_tokens()
    if not tokens:
        raise Exception("Failed to load tokens. No tokens available for processing. Please wait for tokens to load.")
    token = tokens[0]['token']

    encrypted_uid = enc(uid)
    if encrypted_uid is None:
        raise Exception("Encryption of UID failed.")
        
    before = run_async_in_thread(make_async_request(encrypted_uid, server_name, token))
    if before is None:
        raise Exception("Failed to retrieve initial player info.")
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
    app.logger.info(f"Likes before command for UID {uid}: {before_like}")

    if server_name == "IND":
        url = "https://client.ind.freefiremobile.com/LikeProfile"
    elif server_name in {"BR", "US", "SAC", "NA"}:
        url = "https://client.us.freefiremobile.com/LikeProfile"
    else:
        url = "https://clientbp.ggblueshark.com/LikeProfile"

    app.logger.info(f"Sending multiple like requests for UID {uid}...")
    run_async_in_thread(send_multiple_requests(uid, server_name, url))
    after = run_async_in_thread(make_async_request(encrypted_uid, server_name, token))
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
    
    app.logger.info(f"Likes after command for UID {uid}: {after_like}. Given: {like_given}")

    result = {
        "LikesGivenByAPI": like_given,
        "LikesbeforeCommand": before_like,
        "LikesafterCommand": after_like,
        "PlayerNickname": player_name,
        "UID": player_uid,
        "status": status
    }
    return result

@app.route('/like', methods=['GET'])
def handle_requests():
    uid = request.args.get("uid")
    server_name = request.args.get("server_name", "").upper()

    if not uid or not server_name:
        return jsonify({"error": "UID and server_name are required"}), 400

    if not initial_tokens_loaded.is_set():
        app.logger.warning("Tokens are not yet loaded. Waiting for initial load...")
        
        initial_tokens_loaded.wait(timeout=30)
        if not initial_tokens_loaded.is_set():
            return jsonify({"error": "Server is still loading tokens. Please try again in a moment."}), 503

    if not get_available_tokens():
        return jsonify({"error": "No tokens available. Token refresh might have failed."}), 500

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future = executor.submit(process_request_sync_wrapper, uid, server_name)
            result = future.result(timeout=60)
        return jsonify(result)
    except concurrent.futures.TimeoutError:
        app.logger.error(f"Request processing timed out for UID {uid}")
        return jsonify({"error": "Request processing timed out. The server might be overloaded or the Free Fire API is slow."}), 504
    except Exception as e:
        app.logger.exception(f"Error processing request for UID {uid}: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    start_token_refresh_scheduler()
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
