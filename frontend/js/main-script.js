// AWS Cognito 설정
const poolData = {
    UserPoolId: window.APP_CONFIG.USER_POOL_ID, 
    ClientId: window.APP_CONFIG.CLIENT_ID 
};
const userPool = new AmazonCognitoIdentity.CognitoUserPool(poolData);

// 로그인 처리
function handleLogin(e) {
    e.preventDefault();
    const values = getInputValues(loginPopup, ['email', 'password']);
    if (!validateInputs(values)) return;

    const authenticationData = {
        Username: values.email,
        Password: values.password,
    };
    const authenticationDetails = new AmazonCognitoIdentity.AuthenticationDetails(authenticationData);

    const userData = {
        Username: values.email,
        Pool: userPool
    };
    const cognitoUser = new AmazonCognitoIdentity.CognitoUser(userData);

    cognitoUser.authenticateUser(authenticationDetails, {
        onSuccess: function (result) {
            console.log('로그인 성공');
            localStorage.setItem('accessToken', result.getAccessToken().getJwtToken());
            localStorage.setItem('userId', values.email);
            alert('로그인이 성공적으로 완료되었습니다.');
            loginPopup.style.display = "none";
            window.location.href = 'index.html';
        },
        onFailure: function(err) {
            console.error('로그인 실패:', err);
            alert('로그인에 실패했습니다. 다시 시도해주세요.');
        },
    });
}

// 회원가입 처리
function handleSignup(e) {
    e.preventDefault();
    const values = getInputValues(signupPopup, ['email', 'password']);
    if (!validateInputs(values)) return;

    const attributeList = [];
    attributeList.push(new AmazonCognitoIdentity.CognitoUserAttribute({Name:"email",Value:values.email}));

    userPool.signUp(values.email, values.password, attributeList, null, function(err, result){
        if (err) {
            alert(err.message || JSON.stringify(err));
            return;
        }
        cognitoUser = result.user;
        console.log('회원가입 성공. 사용자 이름: ' + cognitoUser.getUsername());
        alert('회원가입이 성공적으로 완료되었습니다. 이메일 인증을 진행해주세요.');
        signupPopup.style.display = "none";
        const verificationPopup = document.getElementById('verificationPopup');
        if (verificationPopup) {
            const verificationEmailInput = verificationPopup.querySelector('input[type="email"]');
            if (verificationEmailInput) {
                verificationEmailInput.value = values.email;
            }
            verificationPopup.style.display = "block";
        } else {
            console.error('이메일 인증 팝업을 찾을 수 없습니다.');
        }
    });
}

document.addEventListener('DOMContentLoaded', function() {
    const loginButton = document.getElementById('loginButton');
    const signupButton = document.getElementById('signupButton');
    const loginPopup = document.getElementById('loginPopup');
    const signupPopup = document.getElementById('signupPopup');
    
    loginButton.onclick = function() {
        loginPopup.style.display = "block";
    }

    signupButton.onclick = function() {
        signupPopup.style.display = "block";
    }

    window.onclick = function(event) {
        if (event.target == loginPopup) {
            loginPopup.style.display = "none";
        }
        if (event.target == signupPopup) {
            signupPopup.style.display = "none";
        }
    }

    // 로그인 팝업의 회원가입 버튼
    loginPopup.querySelector('button:nth-child(5)').onclick = function() {
        loginPopup.style.display = "none";
        signupPopup.style.display = "block";
    }

    // 회원가입 팝업의 로그인 버튼
    signupPopup.querySelector('button:nth-child(5)').onclick = function() {
        signupPopup.style.display = "none";
        loginPopup.style.display = "block";
    }

    // 로그인 팝업의 로그인 버튼
    const loginMainButton = loginPopup.querySelector('button:nth-child(4)');
    if (loginMainButton) {
        loginMainButton.onclick = handleLogin;
    }

    // 회원가입 팝업의 회원가입 버튼
    const signupMainButton = signupPopup.querySelector('button:nth-child(4)');
    if (signupMainButton) {
        signupMainButton.onclick = handleSignup;
    }

    // 이메일 인증 처리
    const verificationPopup = document.getElementById('verificationPopup');
    if (verificationPopup) {
        const verifyButton = verificationPopup.querySelector('button');
        if (verifyButton) {
            verifyButton.onclick = function(e) {
                e.preventDefault();
                const emailInput = verificationPopup.querySelector('input[type="email"]');
                const codeInput = verificationPopup.querySelector('input[type="number"]');
                
                if (!emailInput || !codeInput) {
                    alert('이메일 또는 인증 코드 입력 필드를 찾을 수 없습니다.');
                    return;
                }

                const email = emailInput.value.trim();
                const code = codeInput.value.trim();

                if (!email || !code) {
                    alert('이메일과 인증 코드를 모두 입력해주세요.');
                    return;
                }

                const userData = {
                    Username: email,
                    Pool: userPool
                };
                const cognitoUser = new AmazonCognitoIdentity.CognitoUser(userData);

                cognitoUser.confirmRegistration(code, true, function(err, result) {
                    if (err) {
                        alert(err.message || JSON.stringify(err));
                        return;
                    }
                    console.log('이메일 인증 성공');
                    alert('이메일 인증이 성공적으로 완료되었습니다.');
                    verificationPopup.style.display = "none";
                    loginPopup.style.display = "block";
                });
            }
        }
    }
});

function handleResponse(data, successMessage, successCallback) {
    if (data.statusCode === 200) {
        alert(successMessage);
        successCallback();
    } else {
        alert(`오류: ${data.message || '알 수 없는 오류가 발생했습니다.'}`);
    }
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

function validateInputs(values) {
    for (let key in values) {
        if (!values[key]) {
            alert(`${key}를 입력해주세요.`);
            return false;
        }
    }
    return true;
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