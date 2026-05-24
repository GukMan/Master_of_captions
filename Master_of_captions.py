import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import json
import os
import random
from PIL import Image  # 💡 추가된 이미지 처리 라이브러리

app = FastAPI()

# --- 로컬 이미지 폴더 설정 및 자동 최적화 ---
ORIGINAL_DIR = "Pictures"
OPTIMIZED_DIR = "Optimized_Pictures"

if not os.path.exists(ORIGINAL_DIR):
    os.makedirs(ORIGINAL_DIR)
if not os.path.exists(OPTIMIZED_DIR):
    os.makedirs(OPTIMIZED_DIR)

def optimize_images():
    print("⏳ 이미지 최적화 검사 중...")
    valid_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    for filename in os.listdir(ORIGINAL_DIR):
        ext = os.path.splitext(filename)[1].lower()
        if ext in valid_exts:
            orig_path = os.path.join(ORIGINAL_DIR, filename)
            # gif 파일은 리사이징하면 애니메이션이 깨지므로 원본 그대로 복사(또는 스킵)
            if ext == ".gif":
                opt_path = os.path.join(OPTIMIZED_DIR, filename)
                if not os.path.exists(opt_path):
                    with open(orig_path, "rb") as f_in, open(opt_path, "wb") as f_out:
                        f_out.write(f_in.read())
                continue

            # 최적화된 파일은 무조건 jpg로 통일해서 저장
            opt_filename = os.path.splitext(filename)[0] + ".jpg"
            opt_path = os.path.join(OPTIMIZED_DIR, opt_filename)

            # 이미 최적화된 파일이 없거나, 원본 파일이 최근에 수정된 경우에만 리사이징 실행!
            if not os.path.exists(opt_path) or os.path.getmtime(orig_path) > os.path.getmtime(opt_path):
                try:
                    with Image.open(orig_path) as img:
                        # 투명 배경(PNG) 에러 방지를 위해 RGB 변환
                        if img.mode in ("RGBA", "P"):
                            img = img.convert("RGB")
                        
                        # 가로세로 최대 800px로 비율 유지하며 리사이징 (화질 85%)
                        img.thumbnail((800, 800))
                        img.save(opt_path, format="JPEG", quality=85)
                        print(f"✅ 압축 완료: {filename} -> {opt_filename}")
                except Exception as e:
                    print(f"❌ 이미지 처리 실패 ({filename}): {e}")

# 서버 시작 전 이미지 압축 로직 1회 실행
optimize_images()

# 💡 프론트엔드에는 무거운 원본(Pictures) 대신, 가벼운 최적화 폴더(Optimized_Pictures)를 제공
app.mount("/Pictures", StaticFiles(directory=OPTIMIZED_DIR), name="Pictures")

def get_images():
    valid_exts = {".jpg", ".jpeg"} # 최적화된 파일은 전부 jpg로 변환됨 (gif 제외)
    files = [f"/Pictures/{f}" for f in os.listdir(OPTIMIZED_DIR) if os.path.splitext(f)[1].lower() in valid_exts or f.lower().endswith(".gif")]
    if not files:
        files = [
            "https://images.unsplash.com/photo-1533738363-b7f9aef128ce?w=500&q=80",
            "https://images.unsplash.com/photo-1517849845537-4d257902454a?w=500&q=80"
        ]
    return files

# --- 게임 상태 관리 ---
class GameState:
    def __init__(self):
        self.phase = "waiting" # waiting, roulette, stopping, countdown, voting, result
        self.images = get_images()
        self.current_image = self.images[0] if self.images else ""
        self.current_votes = {"like": 0, "sad": 0}
        self.leaderboard = [] # [{"image": "url", "like": 5, "sad": 2}]
        self.clients = []

    async def broadcast(self):
        state_data = {
            "phase": self.phase,
            "current_image": self.current_image,
            "current_votes": self.current_votes,
            "leaderboard": self.leaderboard,
            "images": self.images
        }
        for client in self.clients:
            try:
                await client.send_text(json.dumps(state_data))
            except Exception:
                pass

game = GameState()

# --- 웹소켓 통신 ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    game.clients.append(websocket)
    await game.broadcast()
    
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            action = message.get("action")

            if action == "start_roulette":
                game.images = get_images()
                game.phase = "roulette"
            elif action == "stop_roulette":
                game.phase = "stopping"
                game.current_image = random.choice(game.images)
            elif action == "start_countdown":
                game.phase = "countdown"
            elif action == "start_voting":
                game.phase = "voting"
                game.current_votes = {"like": 0, "sad": 0}
            elif action == "vote":
                v_type = message.get("type", "like")
                if v_type in game.current_votes:
                    game.current_votes[v_type] += 1
            elif action == "show_results":
                game.phase = "result"
                # 명예의 전당에 기록 저장 (가장 최근 것이 위로 오게)
                game.leaderboard.insert(0, {
                    "image": game.current_image,
                    "like": game.current_votes["like"],
                    "sad": game.current_votes["sad"]
                })
            elif action == "reset":
                game.phase = "waiting"
            elif action == "clear_leaderboard":
                game.leaderboard = []
                
            await game.broadcast()
            
    except WebSocketDisconnect:
        game.clients.remove(websocket)

# --- 프론트엔드 라우팅 ---
@app.get("/")
async def get_host_page():
    return HTMLResponse(HOST_HTML)

@app.get("/player")
async def get_player_page():
    return HTMLResponse(PLAYER_HTML)

# ==========================================
# 1. 호스트(전광판) 화면 코드
# ==========================================
HOST_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <title>🎬 제목 학원 전광판</title>
    <style>
        body { font-family: 'Malgun Gothic', sans-serif; text-align: center; background: #222; color: white; margin:0; padding:20px; position: relative;}
        img { width: 600px; height: 450px; object-fit: contain; border-radius: 10px; margin: 20px; background: #000; box-shadow: 0 0 20px rgba(255,255,255,0.2); }
        .btn { padding: 15px 30px; font-size: 20px; font-weight: bold; cursor: pointer; border: none; border-radius: 8px; margin: 10px; transition: 0.2s; }
        .btn:active { transform: scale(0.95); }
        #startBtn { background: #4CAF50; color: white; }
        #stopBtn { background: #f44336; color: white; display: none; }
        #timer { font-size: 120px; color: #ffeb3b; font-weight: bold; display: none; margin: 10px; text-shadow: 2px 2px 10px rgba(0,0,0,0.5); }
        .highlight { color: #00BCD4; font-size: 35px; margin-top: 10px; }
        
        /* 명예의 전당 UI */
        .board-btn { position: absolute; top: 20px; right: 20px; background: #FFC107; color: black; padding: 10px 20px; border-radius: 5px; font-weight: bold; cursor: pointer; border: none; font-size: 18px;}
        .modal { display: none; position: fixed; top:0; left:0; width: 100%; height: 100%; background: rgba(0,0,0,0.85); z-index: 100; overflow-y: auto; text-align: center;}
        .modal-content { background: #333; margin: 50px auto; padding: 20px; width: 80%; max-width: 700px; border-radius: 10px; border: 2px solid gold;}
        .leader-item { display: flex; align-items: center; justify-content: center; font-size: 30px; border-bottom: 1px solid #555; padding: 15px 0;}
        .leader-item img { width: 120px; height: 90px; object-fit: cover; margin: 0 30px; box-shadow: none;}
        .close-btn { background: #ccc; padding: 10px 20px; margin-top:20px; font-size: 18px; border:none; border-radius:5px; cursor:pointer;}
        .delete-btn { background: #f44336; color: white; padding: 10px 20px; margin-top:20px; font-size: 18px; border:none; border-radius:5px; cursor:pointer;}
    </style>
</head>
<body>
    <button class="board-btn" onclick="toggleLeaderboard(true)">🏆 명예의 전당 보기</button>

    <h1>🎬 제목 학원</h1>
    <h3 style="color:#aaa;">참가자 접속 주소: <b>주소창 뒤에 /player</b></h3>
    
    <div>
        <button id="startBtn" class="btn" onclick="startGame()">START (시작)</button>
        <button id="stopBtn" class="btn" onclick="sendAction('stop_roulette')">STOP (멈추기)</button>
    </div>

    <img id="mainImage" src="" alt="진행 이미지">
    <div id="timer"></div>
    <div id="statusText" class="highlight">준비 완료!</div>

    <div id="nextRoundPanel" style="display:none; margin-top:20px;">
        <button class="btn" style="background:#9C27B0;" onclick="sendAction('reset')">다음 문제로!</button>
    </div>

    <!-- 명예의 전당 모달 창 -->
    <div id="leaderboardModal" class="modal">
        <div class="modal-content">
            <h2 style="color: gold; margin-top:0;">🏆 명예의 전당 🏆</h2>
            <div id="leaderboardList"></div>
            <button class="close-btn" onclick="toggleLeaderboard(false)">닫기</button>
            <button class="delete-btn" onclick="sendAction('clear_leaderboard')">기록 싹 지우기</button>
        </div>
    </div>

    <script>
        const protocol = location.protocol === "https:" ? "wss:" : "ws:";
        const ws = new WebSocket(`${protocol}//${location.host}/ws`);
        let images = [];
        let rouletteInterval;
        let countdownTimer;
        let currentPhase = ""; 
        let audioCtx;

        function initAudio() {
            if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        }

        function playBeep(freq, duration, type="sine") {
            try {
                if(!audioCtx) return;
                const osc = audioCtx.createOscillator();
                const gain = audioCtx.createGain();
                osc.connect(gain);
                gain.connect(audioCtx.destination);
                osc.frequency.value = freq;
                osc.type = type;
                osc.start();
                gain.gain.exponentialRampToValueAtTime(0.00001, audioCtx.currentTime + duration);
                setTimeout(() => osc.stop(), duration * 1000);
            } catch(e) {}
        }

        ws.onmessage = function(event) {
            const state = JSON.parse(event.data);
            images = state.images;
            updateLeaderboard(state.leaderboard);

            // Phase가 변경되었을 때만 애니메이션/타이머 재시작 (버그 1 해결)
            if (state.phase !== currentPhase) {
                currentPhase = state.phase;
                handlePhaseChange(state);
            }
        };

        function handlePhaseChange(state) {
            document.getElementById("startBtn").style.display = "none";
            document.getElementById("stopBtn").style.display = "none";
            document.getElementById("timer").style.display = "none";
            document.getElementById("nextRoundPanel").style.display = "none";
            clearInterval(rouletteInterval);
            clearInterval(countdownTimer);

            if(state.phase === "waiting") {
                document.getElementById("startBtn").style.display = "inline-block";
                document.getElementById("statusText").innerText = "START 버튼을 누르세요!";
                document.getElementById("mainImage").src = images[0] || "";
            } 
            else if(state.phase === "roulette") {
                document.getElementById("stopBtn").style.display = "inline-block";
                document.getElementById("statusText").innerText = "사진이 섞이고 있습니다!";
                
                // 일반 속도로 룰렛 & 띵-띵- 사운드
                rouletteInterval = setInterval(() => {
                    playBeep(500, 0.05); // 띵
                    document.getElementById("mainImage").src = images[Math.floor(Math.random() * images.length)];
                }, 350);
            } 
            else if(state.phase === "stopping") {
                document.getElementById("statusText").innerText = "멈춥니다!";
                
                // 속도 확 빨라지는 연출 연출
                let speed = 80; // 엄청 빠름
                let ticks = 0;
                
                function fastTick() {
                    if (ticks < 15) { // 1.2초 동안 미친듯이 바뀜
                        playBeep(600, 0.03, "square"); // 날카로운 띵
                        document.getElementById("mainImage").src = images[Math.floor(Math.random() * images.length)];
                        ticks++;
                        setTimeout(fastTick, speed);
                    } else {
                        // 최종 사진 멈춤 & 띠링!
                        playBeep(1200, 0.8);
                        document.getElementById("mainImage").src = state.current_image;
                        setTimeout(() => sendAction('start_countdown'), 1000); // 1초 여운 뒤 카운트다운
                    }
                }
                fastTick();
            } 
            else if(state.phase === "countdown") {
                document.getElementById("mainImage").src = state.current_image;
                startTimer(5, "외치세요!", () => sendAction('start_voting'));
            } 
            else if(state.phase === "voting") {
                document.getElementById("mainImage").src = state.current_image;
                document.getElementById("statusText").innerText = "👍 폰에서 투표해 주세요! 😢";
                startTimer(10, "투표 종료!", () => sendAction('show_results'));
            } 
            else if(state.phase === "result") {
                document.getElementById("mainImage").src = state.current_image;
                document.getElementById("statusText").innerText = "결과가 저장되었습니다.";
                document.getElementById("nextRoundPanel").style.display = "block";
                toggleLeaderboard(true); // 결과창 자동 오픈
            }
        }

        function startGame() {
            initAudio(); // 오디오 권한 획득
            sendAction("start_roulette");
        }

        function sendAction(action) {
            ws.send(JSON.stringify({action: action}));
        }

        function startTimer(seconds, endText, callback) {
            let timeLeft = seconds;
            const timerEl = document.getElementById("timer");
            timerEl.style.display = "block";
            timerEl.innerText = timeLeft;
            
            countdownTimer = setInterval(() => {
                timeLeft--;
                if(timeLeft > 0) {
                    timerEl.innerText = timeLeft;
                } else {
                    clearInterval(countdownTimer);
                    timerEl.innerText = endText;
                    if(callback) callback();
                }
            }, 1000);
        }

        function toggleLeaderboard(show) {
            document.getElementById("leaderboardModal").style.display = show ? "block" : "none";
        }

        function updateLeaderboard(list) {
            const container = document.getElementById("leaderboardList");
            if (list.length === 0) {
                container.innerHTML = "<p style='color:#aaa;'>아직 기록이 없습니다.</p>";
                return;
            }
            let html = "";
            list.forEach((item, idx) => {
                html += `
                <div class="leader-item">
                    <span style="color:#aaa; font-size:20px;">#${list.length - idx}</span>
                    <img src="${item.image}">
                    <span style="color:#4CAF50;">👍 ${item.like}</span> &nbsp;&nbsp;&nbsp; 
                    <span style="color:#2196F3;">😢 ${item.sad}</span>
                </div>`;
            });
            container.innerHTML = html;
        }
    </script>
</body>
</html>
"""

# ==========================================
# 2. 플레이어(리모컨) 화면 코드
# ==========================================
PLAYER_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>📱 제목 학원 리모컨</title>
    <style>
        body { font-family: 'Malgun Gothic', sans-serif; text-align: center; background: #e0e0e0; padding: 10px; margin:0; display: flex; flex-direction: column; align-items: center; min-height: 100vh;}
        img { width: 95%; max-width: 400px; height: 280px; object-fit: contain; border-radius: 10px; background:#000; margin-top:20px; box-shadow: 0 5px 10px rgba(0,0,0,0.3);}
        #status { font-size: 24px; font-weight: bold; color: #333; margin: 20px 0; padding: 15px; background: white; border-radius: 10px; width: 90%; max-width:400px; box-sizing:border-box;}
        
        /* 버튼 컨테이너 (사진 아래 배치) */
        #btnContainer { display: none; justify-content: center; gap: 20px; width: 100%; margin-top: 20px; }
        
        .vote-btn { 
            width: 140px; height: 140px; border-radius: 50%; font-size: 70px; 
            border: 5px solid; cursor: pointer; display: flex; align-items: center; justify-content: center;
            box-shadow: 0 10px 20px rgba(0,0,0,0.2); transition: 0.1s; background: white;
        }
        .vote-btn:active { transform: scale(0.9); }
        .like-btn { border-color: #4CAF50; }
        .sad-btn { border-color: #2196F3; }
        
        .overlay { position: fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.8); color:white; display:flex; align-items:center; justify-content:center; flex-direction:column; z-index:999; }
    </style>
</head>
<body>
    <div id="startOverlay" class="overlay" onclick="enterGame()">
        <h1>화면을 터치해서 입장!</h1>
    </div>

    <h2 style="margin:10px 0;">📱 내 폰은 리모컨!</h2>
    <div id="status">메인 화면을 주목해 주세요.</div>
    <img id="playerImage" src="" style="display:none;">
    
    <!-- 사진 아래에 버튼 배치 (가로로 2개) -->
    <div id="btnContainer">
        <button class="vote-btn like-btn" onclick="castVote('like')">👍</button>
        <button class="vote-btn sad-btn" onclick="castVote('sad')">😢</button>
    </div>

    <script>
        const protocol = location.protocol === "https:" ? "wss:" : "ws:";
        const ws = new WebSocket(`${protocol}//${location.host}/ws`);
        let hasVoted = false;
        let images = [];
        let rouletteInterval;
        let currentPhase = "";

        function enterGame() {
            document.getElementById("startOverlay").style.display = "none";
        }

        ws.onmessage = function(event) {
            const state = JSON.parse(event.data);
            images = state.images;
            
            if (state.phase !== currentPhase) {
                currentPhase = state.phase;
                updateUI(state);
            }
        };

        function updateUI(state) {
            const imgEl = document.getElementById("playerImage");
            const statusEl = document.getElementById("status");
            const btnContainer = document.getElementById("btnContainer");
            
            clearInterval(rouletteInterval);
            imgEl.style.display = "none";
            btnContainer.style.display = "none";
            
            if(state.phase === "waiting") {
                statusEl.innerText = "다음 라운드를 준비 중입니다...";
            } 
            else if(state.phase === "roulette") {
                statusEl.innerText = "룰렛이 돌아갑니다!";
                imgEl.style.display = "block";
                rouletteInterval = setInterval(() => {
                    imgEl.src = images[Math.floor(Math.random() * images.length)];
                }, 350);
            } 
            else if(state.phase === "stopping") {
                statusEl.innerText = "멈춥니다!";
                imgEl.style.display = "block";
                let speed = 80; let ticks = 0;
                function fastTick() {
                    if(ticks < 15) {
                        imgEl.src = images[Math.floor(Math.random() * images.length)];
                        ticks++; setTimeout(fastTick, speed);
                    } else {
                        imgEl.src = state.current_image;
                    }
                }
                fastTick();
            }
            else if(state.phase === "countdown") {
                statusEl.innerText = "5초 안에 제목을 외치세요!";
                imgEl.src = state.current_image;
                imgEl.style.display = "block";
            }
            else if(state.phase === "voting") {
                hasVoted = false; // 새 라운드 투표권 초기화
                statusEl.innerText = "투표하세요! (1인 1표)";
                imgEl.src = state.current_image;
                imgEl.style.display = "block";
                btnContainer.style.display = "flex"; // 버튼 등장
            }
            else if(state.phase === "result") {
                statusEl.innerText = "투표 완료! 전광판을 보세요!";
            }
        }

        function castVote(type) {
            if(hasVoted) return; // 1번만 투표 가능
            hasVoted = true;
            ws.send(JSON.stringify({action: "vote", type: type}));
            
            // 누르자마자 버튼 숨기기
            document.getElementById("btnContainer").style.display = "none";
            document.getElementById("status").innerText = type === 'like' ? "따봉 완료! 👍" : "눈물 완료! 😢";
        }
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"🚀 클라우드 서버가 포트 {port}에서 구동됩니다.")
    uvicorn.run(app, host="0.0.0.0", port=port)
