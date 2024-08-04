const protocol = 'WEBSOCKET';
const endpoint = 'wss://bbu912jlyh.execute-api.us-east-1.amazonaws.com/production/';
const langstate = 'korean'; 

let webSocket;
let isConnected = false;

function addMessage(content, isUser = false) {
    
    const chatMessages = document.getElementById('chatMessages');
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${isUser ? 'user-message' : ''}`;
    messageDiv.dataset.id = currentMessageId;

    const avatarImg = document.createElement('img');
    avatarImg.className = 'avatar';
    avatarImg.src = isUser ? '../img/user.png' : '../img/ai.png';
    avatarImg.alt = isUser ? 'User' : 'ChatGPT';

    const contentDiv = document.createElement('div');
    contentDiv.className = 'content';
    contentDiv.textContent = content;

    contentDiv.innerHTML = content; // textContent 대신 innerHTML 사용

    messageDiv.appendChild(avatarImg);
    messageDiv.appendChild(contentDiv);

    if (!isUser) {  // AI 메시지에만 액션 버튼 추가
        const actionsDiv = document.createElement('div');
        actionsDiv.className = 'message-actions';
        
        const actions = ['복사', '다시 생성', '좋아요', '싫어요'];
        actions.forEach(action => {
            const button = document.createElement('button');
            button.textContent = action;
            button.addEventListener('click', () => handleAction(action, content));
            actionsDiv.appendChild(button);
        });

        messageDiv.appendChild(actionsDiv);
    }

    chatMessages.appendChild(messageDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

let currentMessageId = null;

function addReceivedMessage(requestId, msg) {
    if (currentMessageId === null) {
        // 새 메시지 생성
        currentMessageId = requestId;
        addMessage(msg, false);
    } else {
        // 기존 메시지 업데이트
        updateMessage(currentMessageId, msg);
    }
}

// function updateMessage(messageId, content) {
//     const messageElement = document.querySelector(`.message[data-id="${messageId}"]`);
//     if (messageElement) {
//         const contentElement = messageElement.querySelector('.content');
//         if (contentElement) {
//             contentElement.textContent = content;
//         }
//     }
// }

function updateMessage(messageId, content) {
    const messageElement = document.querySelector(`.message[data-id="${messageId}"]`);
    if (messageElement) {
        const contentElement = messageElement.querySelector('.content');
        if (contentElement) {
            contentElement.innerHTML = content; 
        }
    }
}

function connect(endpoint, type) {
    const ws = new WebSocket(endpoint);

    // ws.onmessage = function (event) {
    //     const response = JSON.parse(event.data);
    //     if (response.request_id) {
    //         console.log('received message: ', response.msg);
    //         addReceivedMessage(response.request_id, response.msg);
    //     }
    // };

    ws.onmessage = function (event) {
        const response = JSON.parse(event.data);
        if (response.request_id) {
            console.log('received message: ', response.msg);
            // 줄바꿈 문자를 HTML의 <br> 태그로 변환
            const formattedMsg = response.msg.replace(/\n/g, '<br>');
            addReceivedMessage(response.request_id, formattedMsg);
        }
    };

    ws.onopen = function () {
        isConnected = true;
        if (type === 'initial') {
            setInterval(ping, 57000);
        }
    };

    ws.onclose = function () {
        isConnected = false;
        ws.close();
    };

    return ws;
}

function ping() {
    if (isConnected) {
        webSocket.send(JSON.stringify({ type: 'ping' }));
    }
}

if (protocol === 'WEBSOCKET') {
    webSocket = connect(endpoint, 'initial');
}

// 공통 함수
function getInputValues(container, inputTypes) {
    const values = {};
    inputTypes.forEach(type => {
        const input = container.querySelector(`input[type="${type}"]`);
        if (input) {
            values[type] = input.value.trim();
        }
    });
    return values;
}

function validateInputs(values) {
    for (let key in values) {
        if (!values[key]) {
            alert(`${key}를 입력해주세요.`);
            return false;
        }
    }
    return true;
}

function sendRequest(url, data) {
    return fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        mode: 'cors',
        body: JSON.stringify(data),
    })
    .then(response => response.json());
}

function handleResponse(data, successMessage, successCallback) {
    if (data.statusCode === 200) {
        alert(successMessage);
        successCallback();
    } else {
        alert(`오류: ${data.message || '알 수 없는 오류가 발생했습니다.'}`);
    }
}

// 로그아웃 처리
function handleLogout() { 
    localStorage.removeItem('accessToken');
    localStorage.removeItem('userId');
    alert('로그아웃되었습니다.');
    window.location.href = 'main.html';
}

// 권한이 없는 경우 처리
function handleUnauthorized() {
    alert('접근 권한이 없습니다. 로그인 후 이용해주세요.');
    window.location.href = 'main.html';
}

// 인가 처리
function validateToken() {
    
    const accessToken = localStorage.getItem('accessToken');

    if (!accessToken) {
        console.log('액세스 토큰이 없습니다.');
        handleUnauthorized();
        return;
    }

    // AWS 설정
    AWS.config.region = window.APP_CONFIG.REGION;
    AWS.config.credentials = new AWS.CognitoIdentityCredentials({
        IdentityPoolId: window.APP_CONFIG.USER_POOL_ID
    });

    // Cognito 사용자 풀 설정
    const cognitoidentityserviceprovider = new AWS.CognitoIdentityServiceProvider();

    const params = {
        AccessToken: accessToken
    };

    cognitoidentityserviceprovider.getUser(params, function(err, data) {
        if (err) {
            console.log('토큰 검증 실패:', err);
            handleUnauthorized();
        } else {
            console.log('토큰 검증 성공:', data);
            updateUserInfo(data);
        }
    });
}

function getSelectedModelId() {
    const selectedOption = document.querySelector('.option-ai.selected');
    return selectedOption.querySelector('p').textContent === 'Claude v2.1' ? 'anthropic.claude-v2:1' : 'amazon.titan-text-express-v1';
}

function getSelectedConvType() {
    const selectedOption = document.querySelector('.option-conv.selected');
    return selectedOption.querySelector('p').textContent === '일반 대화' ? 'normal' : 'qa';
}

// 사용자 정보 업데이트
function updateUserInfo(userData) {
    const userEmail = userData.UserAttributes.find(attr => attr.Name === 'email').Value;
    document.getElementById('userEmail').textContent = userEmail;
}

document.addEventListener('DOMContentLoaded', function() {

    validateToken();

    const userInput = document.getElementById('userInput');
    const sendButton = document.getElementById('sendButton');
    const optionsAi = document.querySelectorAll('.option-ai');
    const optionsConv = document.querySelectorAll('.option-conv');
    
    // AI 옵션 선택
    optionsAi.forEach(option => {
        option.addEventListener('click', function() {
            optionsAi.forEach(opt => opt.classList.remove('selected'));
            this.classList.add('selected');
            const selectedModel = this.dataset.model;
            console.log('Selected model:', selectedModel);
        });
    });

    // AI 옵션 선택
    optionsConv.forEach(option => {
        option.addEventListener('click', function() {
            optionsConv.forEach(opt => opt.classList.remove('selected'));
            this.classList.add('selected');
            const selectedModel = this.dataset.model;
            console.log('Selected model:', selectedModel);
        });
    });

    // 로그아웃 버튼
    const logoutButton = document.getElementById('logoutButton');
    if (logoutButton) {
        logoutButton.onclick = handleLogout;
    }

    // 채팅 내역을 가져오는 함수
    async function fetchChatHistory() {

        const userId = localStorage.getItem('userId')
        const allowTime = '2024-07-28T00:00:00Z';
        const url = `https://9gg7p3q32i.execute-api.us-east-1.amazonaws.com/production/history?userId=${userId}&allowTime=${allowTime}`;

        try {
            const response = await fetch(url);
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }
            const data = await response.json();
            console.log('Fetched data:', data);
            return data;
        } catch (error) {
            console.error('Failed to fetch chat history:', error);
            return null;
        }
    }

    // 채팅 내역을 화면에 표시하는 함수
    function displayChatHistory(historyData) {
        console.log(historyData)
        if (!historyData || !historyData.msg) {
            console.error('Invalid history data');
            return;
        }
    
        try {
            const history = JSON.parse(historyData.msg);
            if (Array.isArray(history)) {
                history.forEach(message => {
                    const isUser = message.type === 'text';
                    if (isUser) {
                        addMessage(formatMessage(message.body), true);
                    }
                    if (message.msg) {
                        addMessage(formatMessage(message.msg), false);
                    }
                });
            } else {
                console.error('History is not an array:', history);
            }
        } catch (error) {
            console.error('Error parsing history:', error);
        }
    }
    
    function formatMessage(content) {
        // 줄바꿈 문자를 <br> 태그로 변환
        return content.replace(/\n/g, '<br>');
    }

    // 페이지 로드 시 채팅 내역 가져오기
    fetchChatHistory().then(historyData => {
        if (historyData) {
            displayChatHistory(historyData);
        }
    });

    function handleAction(action, content) {
        console.log(`Action: ${action}, Content: ${content}`);
        switch(action) {
            case '복사':
                navigator.clipboard.writeText(content).then(() => {
                    alert('메시지가 클립보드에 복사되었습니다.');
                });
                break;
            case '다시 생성':
                // ChatGPT API를 호출하여 새로운 응답 생성
                break;
            case '좋아요':
            case '싫어요':
                // 피드백 저장 로직 구현
                break;
        }
    }

    sendButton.addEventListener('click', sendMessage);
    userInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            sendMessage();
        }
    });

    // 초기 메시지 추가
    addMessage("안녕하세요! 어떻게 도와드릴까요?", false);

});

function sendMessage() {
    const message = userInput.value.trim();
    if (message) {
        addMessage(message, true);
        userInput.value = '';
        
        const userId = document.getElementById('userEmail').textContent;
        const requestId = Date.now().toString();
        const requestTime = new Date().toISOString();
        const convType = getSelectedConvType();
        const model_id = getSelectedModelId()

        const messageObj = {
            "user_id": userId,
            "request_id": requestId,
            "request_time": requestTime,
            "type": "text",
            "body": message,
            "conv_type": convType,
            "model_id": model_id
        };

        if (!isConnected) {
            webSocket = connect(endpoint, 'reconnect');
            addMessage("재연결중입니다. 잠시후 다시 시도하세요.", false);
        } else {
            webSocket.send(JSON.stringify(messageObj));
            currentMessageId = null; // 새 메시지 전송 시 currentMessageId 초기화
        }
    }
}