import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import json
import os
import random

app = FastAPI()

# --- 로컬 이미지 폴더 연결 ---
if not os.path.exists("Pictures"):
    os.makedirs("Pictures")
app.mount("/Pictures", StaticFiles(directory="Pictures"), name="Pictures")

def get_images():
    valid_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    files = [f"/Pictures/{f}" for f in os.listdir("Pictures") if os.path.splitext(f)[1].lower() in valid_exts]
    # 폴더가 비어있을 경우를 대비한 기본 이미지
    if not files:
        files = [
            "https://images.unsplash.com/photo-1533738363-b7f9aef128ce?w=500&q=80",
            "https://images.unsplash.com/photo-1517849845537-4d257902454a?w=500&q=80",
            "https://images.unsplash.com/photo-1583337130417-3346a1be7dee?w=500&q=80"
        ]
    return files

# --- 게임 상태 관리 ---
class GameState:
    def __init__(self):
        self.phase = "waiting" # waiting, roulette, slowing, countdown, voting, result
        self.images = get_images()
        self.current_image = self.images[0] if self.images else ""
        self.current_player = ""
        self.current_votes = 0
        self.leaderboard = [] # [{"name": "홍길동", "score": 5}]
        self.clients = []

    async def broadcast(self):
        # 게임 상태가 바뀔 때마다 모든 기기에 화면 동기화
        state_data = {
            "phase": self.phase,
            "current_image": self.current_image,
            "current_player": self.current_player,
            "current_votes": self.current_votes,
            "leaderboard": sorted(self.leaderboard, key=lambda x: x["score"], reverse=True),
            "images": self.images
        }
        for client in self.clients:
            try:
                await client.send_text(json.dumps(state_data))
            except Exception:
                pass

game = GameState()

# --- 웹소켓 (실시간 통신) 관리 ---
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
                game.images = get_images() # 사진 폴더 갱신
                game.current_player = message.get("player_name", "익명")
                game.phase = "roulette"
            elif action == "stop_roulette":
                game.phase = "slowing"
                game.current_image = random.choice(game.images)
            elif action == "start_countdown":
                game.phase = "countdown"
            elif action == "start_voting":
                game.phase = "voting"
                game.current_votes = 0
            elif action == "vote":
                game.current_votes += 1
            elif action == "show_results":
                game.phase = "result"
                game.leaderboard.append({"name": game.current_player, "score": game.current_votes})
            elif action == "reset":
                game.phase = "waiting"
                
            await game.broadcast()
            
    except WebSocketDisconnect:
        game.clients.remove(websocket)

# --- 화면 라우팅 ---
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
        body { font-family: 'Malgun Gothic', sans-serif; text-align: center; background: #222; color: white; margin:0; padding:20px;}
        img { width: 500px; height: 400px; object-fit: contain; border-radius: 10px; margin: 20px; background: #000; box-shadow: 0 0 20px rgba(255,255,255,0.2); }
        .btn { padding: 15px 30px; font-size: 20px; font-weight: bold; cursor: pointer; border: none; border-radius: 8px; margin: 10px; transition: 0.2s; }
        .btn:active { transform: scale(0.95); }
        #startBtn { background: #4CAF50; color: white; }
        #stopBtn { background: #f44336; color: white; display: none; }
        #timer { font-size: 100px; color: #ffeb3b; font-weight: bold; display: none; margin: 20px; text-shadow: 2px 2px 10px rgba(0,0,0,0.5); }
        .panel { display: none; margin-top: 20px; }
        input { padding: 15px; font-size: 20px; border-radius: 8px; border:none; text-align:center; width: 200px; font-weight:bold;}
        .highlight { color: #00BCD4; font-size: 30px; }
    </style>
</head>
<body>
    <h1>🎬 제목 학원</h1>
    <h3 style="color:#aaa;">참가자 접속 주소: <b>주소창 뒤에 /player</b></h3>
    
    <div id="setupPanel">
        <input type="text" id="playerName" placeholder="도전자 이름 입력">
        <button id="startBtn" class="btn" onclick="startGame()">START</button>
    </div>
    
    <div>
        <button id="stopBtn" class="btn" onclick="sendAction('stop_roulette')">STOP (멈추기)</button>
    </div>

    <img id="mainImage" src="" alt="진행 이미지">
    <div id="timer"></div>
    <div id="statusText" class="highlight"></div>

    <div id="resultPanel" class="panel">
        <h2 style="color: gold;">🏆 명예의 전당 🏆</h2>
        <ul id="leaderboard" style="list-style:none; padding:0; font-size: 28px;"></ul>
        <button class="btn" style="background:#9C27B0;" onclick="sendAction('reset')">다음 도전자!</button>
    </div>

    <script>
        const protocol = location.protocol === "https:" ? "wss:" : "ws:";
        const ws = new WebSocket(`${protocol}//${location.host}/ws`);
        let images = [];
        let rouletteInterval;
        let countdownTimer;

        // 효과음 생성기 (웹 오디오 API)
        function playBeep(freq, duration) {
            try {
                const ctx = new (window.AudioContext || window.webkitAudioContext)();
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.connect(gain);
                gain.connect(ctx.destination);
                osc.frequency.value = freq;
                osc.type = "sine";
                osc.start();
                gain.gain.exponentialRampToValueAtTime(0.00001, ctx.currentTime + duration);
                setTimeout(() => ctx.close(), duration * 1000);
            } catch(e) {}
        }

        ws.onmessage = function(event) {
            const state = JSON.parse(event.data);
            images = state.images;
            
            // UI 초기화
            document.getElementById("setupPanel").style.display = "none";
            document.getElementById("stopBtn").style.display = "none";
            document.getElementById("timer").style.display = "none";
            document.getElementById("resultPanel").style.display = "none";
            document.getElementById("statusText").innerText = "";
            clearInterval(rouletteInterval);
            clearInterval(countdownTimer);

            if(state.phase === "waiting") {
                document.getElementById("setupPanel").style.display = "block";
                document.getElementById("playerName").value = "";
                document.getElementById("mainImage").src = images[0] || "";
            } 
            else if(state.phase === "roulette") {
                document.getElementById("stopBtn").style.display = "inline-block";
                document.getElementById("statusText").innerText = `[${state.current_player}]님의 순서입니다!`;
                
                // 0.5초(500ms)마다 이미지 룰렛
                rouletteInterval = setInterval(() => {
                    document.getElementById("mainImage").src = images[Math.floor(Math.random() * images.length)];
                }, 500);
            } 
            else if(state.phase === "slowing") {
                // 점점 느려지는 애니메이션 (호스트가 템포 조절)
                let delay = 300;
                let ticks = 0;
                
                function slowDownTick() {
                    if (ticks < 4) {
                        playBeep(600, 0.1); // 띵
                        document.getElementById("mainImage").src = images[Math.floor(Math.random() * images.length)];
                        delay += 300;
                        ticks++;
                        setTimeout(slowDownTick, delay);
                    } else {
                        playBeep(1000, 0.5); // 띠링!
                        document.getElementById("mainImage").src = state.current_image; // 최종 선택된 사진 고정
                        // 1초 뒤 자동으로 카운트다운 시작
                        setTimeout(() => sendAction('start_countdown'), 1000);
                    }
                }
                slowDownTick();
            } 
            else if(state.phase === "countdown") {
                document.getElementById("mainImage").src = state.current_image;
                startTimer(5, "외치세요!", () => sendAction('start_voting'));
            } 
            else if(state.phase === "voting") {
                document.getElementById("mainImage").src = state.current_image;
                document.getElementById("statusText").innerText = "👍 폰에서 따봉을 눌러주세요!";
                startTimer(10, "투표 종료!", () => sendAction('show_results'));
            } 
            else if(state.phase === "result") {
                document.getElementById("mainImage").src = state.current_image;
                document.getElementById("resultPanel").style.display = "block";
                let html = "";
                state.leaderboard.forEach((c, idx) => {
                    html += `<li style="margin:15px;">${idx+1}위: [${c.name}] - <b>${c.score} 따봉 👍</b></li>`;
                });
                document.getElementById("leaderboard").innerHTML = html;
            }
        };

        function sendAction(action) {
            ws.send(JSON.stringify({action: action}));
        }

        function startGame() {
            const name = document.getElementById("playerName").value || "익명";
            ws.send(JSON.stringify({action: "start_roulette", player_name: name}));
        }

        // 공통 타이머 함수
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
        body { font-family: 'Malgun Gothic', sans-serif; text-align: center; background: #e0e0e0; padding: 10px; margin:0;}
        img { width: 90%; max-width: 400px; height: 250px; object-fit: contain; border-radius: 10px; background:#000; margin-top:10px; box-shadow: 0 5px 10px rgba(0,0,0,0.3);}
        #status { font-size: 22px; font-weight: bold; color: #333; margin: 20px 0; padding: 10px; background: white; border-radius: 10px;}
        .vote-btn { 
            display: none; width: 200px; height: 200px; border-radius: 50%; font-size: 80px; 
            background: #FFEB3B; border: 5px solid #FFC107; cursor: pointer; margin: 20px auto; 
            box-shadow: 0 10px 20px rgba(0,0,0,0.2); transition: 0.1s;
        }
        .vote-btn:active { transform: scale(0.9); background: #FFC107; }
        .overlay { position: fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.8); color:white; display:flex; align-items:center; justify-content:center; flex-direction:column; z-index:999; }
    </style>
</head>
<body>
    <!-- 모바일 브라우저 오디오 재생 권한 획득용 -->
    <div id="startOverlay" class="overlay" onclick="enterGame()">
        <h1>화면을 터치해서 입장!</h1>
        <p>효과음 재생을 위해 터치가 필요합니다.</p>
    </div>

    <h2 style="margin:5px 0;">📱 내 폰은 리모컨!</h2>
    <div id="status">메인 화면을 주목해 주세요.</div>
    <img id="playerImage" src="" style="display:none;">
    
    <button id="ddabongBtn" class="vote-btn" onclick="castVote()">👍</button>

    <script>
        const protocol = location.protocol === "https:" ? "wss:" : "ws:";
        const ws = new WebSocket(`${protocol}//${location.host}/ws`);
        let hasVoted = false;
        let images = [];
        let rouletteInterval;

        function playBeep(freq, duration) {
            try {
                const ctx = new (window.AudioContext || window.webkitAudioContext)();
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.connect(gain);
                gain.connect(ctx.destination);
                osc.frequency.value = freq;
                osc.type = "sine";
                osc.start();
                gain.gain.exponentialRampToValueAtTime(0.00001, ctx.currentTime + duration);
                setTimeout(() => ctx.close(), duration * 1000);
            } catch(e) {}
        }

        function enterGame() {
            document.getElementById("startOverlay").style.display = "none";
            // 침묵 소리 재생으로 오디오 컨텍스트 뚫어놓기
            playBeep(0, 0.1); 
        }

        ws.onmessage = function(event) {
            const state = JSON.parse(event.data);
            images = state.images;
            const imgEl = document.getElementById("playerImage");
            const statusEl = document.getElementById("status");
            const btnEl = document.getElementById("ddabongBtn");
            
            clearInterval(rouletteInterval);
            imgEl.style.display = "none";
            btnEl.style.display = "none";
            
            if(state.phase === "waiting") {
                statusEl.innerText = "다음 도전자를 기다리는 중...";
            } 
            else if(state.phase === "roulette") {
                statusEl.innerText = `[${state.current_player}]님의 룰렛이 돌아갑니다!`;
                imgEl.style.display = "inline-block";
                rouletteInterval = setInterval(() => {
                    imgEl.src = images[Math.floor(Math.random() * images.length)];
                }, 500);
            } 
            else if(state.phase === "slowing") {
                statusEl.innerText = "멈춥니다...";
                imgEl.style.display = "inline-block";
                let delay = 300; let ticks = 0;
                function slowTick() {
                    if(ticks < 4) {
                        playBeep(600, 0.1);
                        imgEl.src = images[Math.floor(Math.random() * images.length)];
                        delay += 300; ticks++;
                        setTimeout(slowTick, delay);
                    } else {
                        playBeep(1000, 0.5);
                        imgEl.src = state.current_image;
                    }
                }
                slowTick();
            }
            else if(state.phase === "countdown") {
                statusEl.innerText = "5초 안에 제목을 외치세요!";
                imgEl.src = state.current_image;
                imgEl.style.display = "inline-block";
            }
            else if(state.phase === "voting") {
                hasVoted = false; // 새 라운드 투표권 초기화
                statusEl.innerText = "지금입니다! 따봉을 눌러주세요!";
                imgEl.src = state.current_image;
                imgEl.style.display = "inline-block";
                btnEl.style.display = "inline-block";
            }
            else if(state.phase === "result") {
                statusEl.innerText = "투표 완료! 전광판을 보세요!";
            }
        };

        function castVote() {
            if(hasVoted) return alert("이미 따봉을 눌렀습니다!");
            hasVoted = true;
            ws.send(JSON.stringify({action: "vote"}));
            document.getElementById("ddabongBtn").style.display = "none";
            document.getElementById("status").innerText = "따봉 완료! 👍";
        }
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"🚀 클라우드 서버가 포트 {port}에서 구동됩니다.")
    uvicorn.run(app, host="0.0.0.0", port=port)
