import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import json
import os

app = FastAPI()


# --- 게임 상태 관리 ---
class GameState:
    def __init__(self):
        self.phase = "waiting"  # waiting, roulette, countdown, voting, result
        self.current_image = "https://images.unsplash.com/photo-1533738363-b7f9aef128ce?w=500&q=80"  # 기본 고양이 짤
        self.images = [
            "https://images.unsplash.com/photo-1533738363-b7f9aef128ce?w=500&q=80",
            "https://images.unsplash.com/photo-1517849845537-4d257902454a?w=500&q=80",
            "https://images.unsplash.com/photo-1583337130417-3346a1be7dee?w=500&q=80"
        ]
        self.candidates = []  # [{"id": 0, "title": "제목", "author": "작성자", "votes": 0}]
        self.clients = []

    async def broadcast(self):
        state_data = {
            "phase": self.phase,
            "current_image": self.current_image,
            "candidates": self.candidates
        }
        for client in self.clients:
            try:
                await client.send_text(json.dumps(state_data))
            except Exception:
                pass


game = GameState()


# --- 웹소켓 연결 관리 ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    game.clients.append(websocket)
    await game.broadcast()  # 접속 시 현재 상태 전송

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            action = message.get("action")

            if action == "start_roulette":
                game.phase = "roulette"
            elif action == "stop_roulette":
                game.phase = "countdown"
                import random
                game.current_image = random.choice(game.images)
            elif action == "start_voting":
                game.phase = "voting"
                game.candidates = message.get("candidates", [])
            elif action == "vote":
                c_id = message.get("candidate_id")
                for c in game.candidates:
                    if c["id"] == c_id:
                        c["votes"] += 1
            elif action == "show_results":
                game.phase = "result"
                game.candidates.sort(key=lambda x: x["votes"], reverse=True)
            elif action == "reset":
                game.phase = "waiting"
                game.candidates = []

            await game.broadcast()

    except WebSocketDisconnect:
        game.clients.remove(websocket)


# --- 화면 라우팅 (HTML) ---
@app.get("/")
async def get_host_page():
    return HTMLResponse(HOST_HTML)


@app.get("/player")
async def get_player_page():
    return HTMLResponse(PLAYER_HTML)


# --- 프론트엔드 HTML/JS (HTTPS/WSS 호환 적용) ---
HOST_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <title>제목 학원 - 호스트 화면</title>
    <style>
        body { font-family: 'Malgun Gothic', sans-serif; text-align: center; background: #222; color: white; }
        img { max-width: 500px; max-height: 400px; border-radius: 10px; margin: 20px; transition: transform 0.1s; }
        .btn { padding: 15px 30px; font-size: 20px; font-weight: bold; cursor: pointer; border: none; border-radius: 5px; margin: 10px; }
        #startBtn { background: #4CAF50; color: white; }
        #stopBtn { background: #f44336; color: white; display: none; }
        #timer { font-size: 80px; color: #ffeb3b; font-weight: bold; display: none; margin: 20px; }
        .panel { display: none; margin-top: 20px; }
        input { padding: 10px; font-size: 16px; margin: 5px; }
        .roulette-anim { animation: shake 0.5s infinite; filter: blur(2px); }
        @keyframes shake { 0% { transform: translate(1px, 1px) rotate(0deg); } 10% { transform: translate(-1px, -2px) rotate(-1deg); } 20% { transform: translate(-3px, 0px) rotate(1deg); } 30% { transform: translate(3px, 2px) rotate(0deg); } 40% { transform: translate(1px, -1px) rotate(1deg); } }
    </style>
</head>
<body>
    <h1>🎬 제목 학원 (메인 전광판)</h1>
    <h3 style="color:#aaa;">참가자들은 스마트폰으로 주소 뒤에 <b>/player</b> 를 붙여서 접속하세요!</h3>

    <img id="mainImage" src="https://images.unsplash.com/photo-1533738363-b7f9aef128ce?w=500&q=80" alt="진행 이미지">
    <div id="timer">5</div>

    <div>
        <button id="startBtn" class="btn" onclick="sendAction('start_roulette')">START (룰렛 돌리기)</button>
        <button id="stopBtn" class="btn" onclick="sendAction('stop_roulette')">STOP (사진 멈추기)</button>
    </div>

    <div id="inputPanel" class="panel">
        <h3>🎙️ 사람들이 외친 재미있는 제목을 입력하세요</h3>
        <input type="text" id="author1" placeholder="참가자 이름"> <input type="text" id="title1" placeholder="제목 1"><br>
        <input type="text" id="author2" placeholder="참가자 이름"> <input type="text" id="title2" placeholder="제목 2"><br>
        <button class="btn" style="background:#2196F3;" onclick="startVoting()">투표 시작하기</button>
    </div>

    <div id="resultPanel" class="panel">
        <h2 style="color: gold;">🏆 투표 결과 🏆</h2>
        <ul id="leaderboard" style="list-style:none; padding:0; font-size: 24px;"></ul>
        <button class="btn" style="background:#9C27B0;" onclick="sendAction('reset')">다음 라운드</button>
    </div>

    <script>
        // 클라우드 HTTPS 환경 대응 (wss:// 자동 전환)
        const protocol = location.protocol === "https:" ? "wss:" : "ws:";
        const ws = new WebSocket(`${protocol}//${location.host}/ws`);
        let countdown;

        ws.onmessage = function(event) {
            const state = JSON.parse(event.data);
            document.getElementById("mainImage").src = state.current_image;

            document.getElementById("startBtn").style.display = "none";
            document.getElementById("stopBtn").style.display = "none";
            document.getElementById("timer").style.display = "none";
            document.getElementById("inputPanel").style.display = "none";
            document.getElementById("resultPanel").style.display = "none";
            document.getElementById("mainImage").classList.remove("roulette-anim");

            if(state.phase === "waiting") {
                document.getElementById("startBtn").style.display = "inline-block";
            } else if(state.phase === "roulette") {
                document.getElementById("stopBtn").style.display = "inline-block";
                document.getElementById("mainImage").classList.add("roulette-anim");
            } else if(state.phase === "countdown") {
                startTimer();
            } else if(state.phase === "voting") {
                document.getElementById("resultPanel").style.display = "block";
                document.getElementById("leaderboard").innerHTML = "<li>참가자들이 투표 중입니다... (1인 1표)</li>";
                document.getElementById("resultPanel").innerHTML += `<button class="btn" style="background:#FF9800;" onclick="sendAction('show_results')">결과 공개!</button>`;
            } else if(state.phase === "result") {
                document.getElementById("resultPanel").style.display = "block";
                let html = "";
                state.candidates.forEach((c, idx) => {
                    html += `<li style="margin:10px;">${idx+1}위: [${c.author}] ${c.title} - <b>${c.votes}표</b></li>`;
                });
                document.getElementById("leaderboard").innerHTML = html;
            }
        };

        function sendAction(action) {
            ws.send(JSON.stringify({action: action}));
        }

        function startTimer() {
            let timeLeft = 5;
            const timerEl = document.getElementById("timer");
            timerEl.style.display = "block";
            timerEl.innerText = timeLeft;

            countdown = setInterval(() => {
                timeLeft--;
                timerEl.innerText = timeLeft;
                if(timeLeft <= 0) {
                    clearInterval(countdown);
                    timerEl.innerText = "타임 오버!";
                    document.getElementById("inputPanel").style.display = "block";
                }
            }, 1000);
        }

        function startVoting() {
            const candidates = [];
            if(document.getElementById("title1").value) candidates.push({id:1, author: document.getElementById("author1").value, title: document.getElementById("title1").value, votes:0});
            if(document.getElementById("title2").value) candidates.push({id:2, author: document.getElementById("author2").value, title: document.getElementById("title2").value, votes:0});
            ws.send(JSON.stringify({action: "start_voting", candidates: candidates}));
        }
    </script>
</body>
</html>
"""

PLAYER_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>제목 학원 - 리모컨</title>
    <style>
        body { font-family: 'Malgun Gothic', sans-serif; text-align: center; background: #e0e0e0; padding: 20px; }
        .vote-btn { display: block; width: 100%; padding: 20px; margin: 10px 0; font-size: 20px; background: #fff; border: 2px solid #ccc; border-radius: 10px; cursor: pointer; }
        .vote-btn:active { background: #dcedc8; }
        #status { font-size: 24px; font-weight: bold; color: #333; margin-top: 50px; }
    </style>
</head>
<body>
    <h2>📱 내 폰은 리모컨!</h2>
    <div id="status">메인 화면을 주목해 주세요.</div>
    <div id="votePanel" style="display:none;">
        <h3>가장 웃긴 제목에 투표하세요!</h3>
        <div id="candidates"></div>
    </div>

    <script>
        const protocol = location.protocol === "https:" ? "wss:" : "ws:";
        const ws = new WebSocket(`${protocol}//${location.host}/ws`);
        let hasVoted = false;

        ws.onmessage = function(event) {
            const state = JSON.parse(event.data);

            if(state.phase === "voting") {
                hasVoted = false;
                document.getElementById("status").style.display = "none";
                document.getElementById("votePanel").style.display = "block";

                let html = "";
                state.candidates.forEach(c => {
                    html += `<button class="vote-btn" onclick="castVote(${c.id})">"${c.title}"<br><small>by ${c.author}</small></button>`;
                });
                document.getElementById("candidates").innerHTML = html;
            } else {
                document.getElementById("votePanel").style.display = "none";
                document.getElementById("status").style.display = "block";
                if(state.phase === "waiting") document.getElementById("status").innerText = "다음 게임을 준비 중입니다...";
                if(state.phase === "roulette") document.getElementById("status").innerText = "룰렛이 돌아갑니다! 준비하세요!";
                if(state.phase === "countdown") document.getElementById("status").innerText = "5초 카운트다운! 빨리 제목을 외치세요!";
                if(state.phase === "result") document.getElementById("status").innerText = "전광판에서 결과를 확인하세요!";
            }
        };

        function castVote(id) {
            if(hasVoted) return alert("이미 투표하셨습니다!");
            hasVoted = true;
            ws.send(JSON.stringify({action: "vote", candidate_id: id}));
            document.getElementById("votePanel").style.display = "none";
            document.getElementById("status").style.display = "block";
            document.getElementById("status").innerText = "투표 완료! 결과를 기다리세요.";
        }
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    # Render 등의 클라우드가 주는 동적 포트를 감지하고 없으면 8000번을 씁니다.
    port = int(os.environ.get("PORT", 8000))
    print(f"🚀 클라우드 서버가 포트 {port}에서 구동됩니다.")
    uvicorn.run(app, host="0.0.0.0", port=port)
