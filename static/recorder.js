const socket = io.connect("http://localhost:8088");
let recording = false;
let observer; // MutationObserver를 위한 변수 선언

function openURL() {
    const url = document.getElementById("url").value;
    const proxiedUrl = `/proxy?url=${encodeURIComponent(url)}`;
    document.getElementById("actionFrame").src = proxiedUrl;
    document.getElementById("status").innerText = `Loaded ${url} in the frame`;
}

function startRecording() {
    const iframe = document.getElementById("actionFrame").contentWindow;
    recording = true;

    // 클릭 이벤트 기록
    iframe.document.addEventListener("click", (e) => {
        if (recording) {
            storeLastInputValue();  // 클릭 발생 시 마지막 input 값 기록
            const action = {
                type: "click",
                selector: getSelector(e.target),
            };
            socket.emit("record_action", action);
            console.log("Recorded click:", action);
        }
    });

    // input 이벤트를 사용하여 최종 값이 변경될 때마다 기록
    iframe.document.addEventListener("input", (e) => {
        if (recording && e.target.tagName.toLowerCase() === "input") {
            storeLastInputValue(e.target);
        }
    });
}

// 최종 input 값을 저장하는 함수
function storeLastInputValue(focusedInput) {
    if (focusedInput && focusedInput.value) {
        const action = {
            type: "input",
            selector: getSelector(focusedInput),
            value: focusedInput.value,
        };
        socket.emit("record_action", action);
        console.log("Stored final input:", action);
    }
}

// 저장된 시나리오를 서버에 전송
function saveScenario() {
    const scenarioName = prompt("Enter a name for the scenario:");
    socket.emit("save_scenario", { name: scenarioName });
}

// 시나리오 실행
function playScenario() {
    const scenarioName = prompt("Enter the name of the scenario to play:");
    socket.emit("play_scenario", { name: scenarioName });

    socket.on("play_scenario_action", async (action) => {
        const iframe = document.getElementById("actionFrame").contentWindow.document;
        console.log(action.type);
        // 액션에 따라 동작 수행
        if (action.type === "click") {
            const element = iframe.querySelector(action.selector);
            if (element) element.click();
        } else if (action.type === "input") {
            const element = iframe.querySelector(action.selector);
            if (element && action.value) {
                console.log(action.value);
                await typeText(element, action.value); // 한 글자씩 입력하도록 typeText 함수 호출
            }
        } else if (action.type === "key") {
            const element = iframe.querySelector(action.selector);
            if (element) {
                const keyEvent = new KeyboardEvent('keydown', { key: action.key, bubbles: true });
                element.dispatchEvent(keyEvent);
            }
        }
    });
}

async function typeText(element, text) {
    for (let char of text) {
        element.value += char;  // 개별 문자 입력
        const inputEvent = new Event('input', { bubbles: true });
        element.dispatchEvent(inputEvent);
        await new Promise(resolve => setTimeout(resolve, 100));  // 지연 시간 추가
    }
}


// CSS 셀렉터 추출
function getSelector(element) {
    return element.tagName.toLowerCase() + (element.id ? "#" + element.id : "");
}

// 서버 상태 메시지 수신
socket.on("status", (data) => {
    document.getElementById("status").innerText = data.message;
});
