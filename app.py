import eventlet
eventlet.monkey_patch()     # 필수 설정

import requests
from flask import Flask, render_template, request, jsonify, Response, session, redirect
from flask_socketio import SocketIO, emit
from flask_cors import CORS
from urllib.parse import urlparse, urljoin
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import UnexpectedAlertPresentException, NoAlertPresentException, NoSuchWindowException, WebDriverException, NoSuchElementException
from bs4 import BeautifulSoup  # HTML 파싱을 위한 라이브러리
import json
import time

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")  # async_mode 설정
CORS(app)

# 시나리오 파일 저장 경로
SCENARIO_PATH = "scenarios/"
recorded_actions = []

# 브라우저 드라이버 설정
driver = webdriver.Chrome()

def modify_html(base_url, content):
    """HTML의 상대 경로를 절대 프록시 경로로 변환"""
    soup = BeautifulSoup(content, "html.parser")
    
    # img, script, link 태그의 src/href 속성을 수정하여 프록시 경로로 변환
    for tag in soup.find_all(["img", "script", "link"]):
        attr = "src" if tag.name == "img" or tag.name == "script" else "href"
        if tag.has_attr(attr):
            original_url = tag[attr]
            if not urlparse(original_url).netloc:  # 상대 경로일 때만 변환
                tag[attr] = f"/proxy_resource?url={urljoin(base_url, original_url)}"
    
    # CSS 내 url() 참조 리소스 변환
    for style_tag in soup.find_all("style"):
        if style_tag.string:
            style_content = style_tag.string.replace("url(/", f"url({base_url}/")
            style_tag.string.replace_with(style_content)
    
    return str(soup)

@app.route('/proxy')
def proxy():
    target_url = request.args.get('url')
    if not target_url:
        return "URL is required", 400

    # 요청된 URL의 HTML 콘텐츠 가져오기
    response = requests.get(target_url)
    session['base_url'] = '{uri.scheme}://{uri.netloc}'.format(uri=urlparse(target_url))
    modified_content = modify_html(session['base_url'], response.content)
    return Response(modified_content, content_type="text/html")

@app.route('/proxy_resource')
def proxy_resource():
    target_url = request.args.get('url')
    if not target_url:
        return "URL is required", 400

    # 리소스 가져오기
    response = requests.get(target_url, allow_redirects=True)
    response_content = response.content  # 모든 청크를 로드
    content_length = len(response_content)  # 콘텐츠 길이 계산

    # JavaScript MIME 타입 설정 강화
    content_type = response.headers.get('Content-Type')
    if target_url.endswith('.js') or ('javascript' in content_type if content_type else False):
        content_type = 'application/javascript'
    
    # X-Frame-Options, Content-Security-Policy, 및 X-Content-Type-Options 헤더 설정
    headers = {
        key: value for key, value in response.headers.items()
        if key.lower() not in ['x-frame-options', 'content-security-policy']
    }
    headers['X-Content-Type-Options'] = 'nosniff'
    headers['Content-Length'] = str(content_length)  # Content-Length 헤더 설정
    
    return Response(response_content, headers=headers, content_type=content_type)

@app.route('/<path:path>', methods=['GET'])
def catch_all(path):
    base_url = session.get('base_url')
    if not base_url:
        return "Base URL is not set", 400
    
    # 최종 URL 생성 및 요청
    target_url = urljoin(base_url, path)
    response = requests.get(target_url, allow_redirects=True)
    response_content = response.content  # 모든 청크를 로드
    content_length = len(response_content)  # 콘텐츠 길이 계산

    # JavaScript MIME 타입 설정 강화
    content_type = response.headers.get('Content-Type')
    if target_url.endswith('.js') or ('javascript' in content_type if content_type else False):
        content_type = 'application/javascript'
    
    # X-Frame-Options, Content-Security-Policy, 및 X-Content-Type-Options 헤더 설정
    headers = {
        key: value for key, value in response.headers.items()
        if key.lower() not in ['x-frame-options', 'content-security-policy']
    }
    headers['X-Content-Type-Options'] = 'nosniff'
    headers['Content-Length'] = str(content_length)  # Content-Length 헤더 설정
    
    return Response(response_content, headers=headers, content_type=content_type)

@app.route('/')
def index():
    return render_template('index.html')

# 특정 URL을 Selenium 브라우저로 열기
@socketio.on('open_url')
def open_url(data):
    url = data['url']
    driver.get(url)
    emit('status', {'message': f'{url} opened in browser'})

# 사용자 액션 기록
# 사용자 액션 기록
@socketio.on('record_action')
def record_action(data):
    action_type = data['type']
    
    if action_type == 'input':
        # `input` 타입의 액션은 전체 문자열로 기록
        recorded_actions.append({
            'type': 'input',
            'selector': data['selector'],
            'value': data['value']
        })
    
    elif action_type == 'key':
        # `key` 타입의 동작은 개별 키로 기록
        recorded_actions.append({
            'type': 'key',
            'selector': data['selector'],
            'key': data['key']
        })
    
    else:
        recorded_actions.append(data)
    
    emit('status', {'message': 'Action recorded'})


# 시나리오 저장
@socketio.on('save_scenario')
def save_scenario(data):
    scenario_name = data['name']
    with open(SCENARIO_PATH + scenario_name + ".json", 'w') as f:
        json.dump(recorded_actions, f)
    emit('status', {'message': 'Scenario saved'})

# 시나리오 재생
@socketio.on('play_scenario')
def play_scenario(data):
    scenario_name = data['name']
    with open(SCENARIO_PATH + scenario_name + ".json") as f:
        actions = json.load(f)

    try:
        # 창 상태 확인
        if not driver.window_handles:
            emit('status', {'message': 'No active browser window. Re-opening URL...'})
            open_url({'url': 'your_default_url_here'})  # 초기 URL을 다시 열기

        for action in actions:
            execute_action(action)

        emit('status', {'message': 'Scenario played successfully'})

    except NoSuchWindowException:
        emit('status', {'message': 'Browser window was closed. Please restart the browser session.'})
    except WebDriverException as e:
        emit('status', {'message': f'Unexpected error: {str(e)}'})

# 기록된 액션을 Selenium으로 실행
def execute_action(action):
    try:
        # 프레임 이동
        if 'iframe_selector' in action:
            iframe = driver.find_element(By.CSS_SELECTOR, action['iframe_selector'])
            driver.switch_to.frame(iframe)

        # 엘리먼트 찾기
        element = driver.find_element(By.CSS_SELECTOR, action['selector'])

        # 포커스 맞추기
        driver.execute_script("arguments[0].scrollIntoView();", element)
        element.click()  # 포커스를 위한 클릭
        time.sleep(0.1)  # 포커스 대기

        # 액션 타입별 처리
        if action['type'] == 'click':
            element.click()

        elif action['type'] == 'input':
            # JavaScript로 값을 설정 (Selenium send_keys 대체)
            driver.execute_script("arguments[0].setAttribute('value', arguments[1])", element, action['value'])
            time.sleep(0.1)  # 적용 대기

        elif action['type'] == 'key':
            # 키 입력 동작 수행
            if action['key'] == 'backspace':
                element.send_keys(Keys.BACKSPACE)
            elif action['key'] == 'ctrl+a':
                element.send_keys(Keys.CONTROL, 'a')
            elif action['key'] == 'enter':
                element.send_keys(Keys.ENTER)
            elif action['key'] == 'tab':
                element.send_keys(Keys.TAB)
            # 추가 키 처리 가능

        elif action['type'] == 'scroll':
            ActionChains(driver).move_to_element(element).perform()

        # alert 처리 및 스크린샷 저장
        try:
            alert = driver.switch_to.alert
            alert.accept()
        except NoAlertPresentException:
            pass

        driver.save_screenshot(f"screenshots/{int(time.time())}.png")

    except NoSuchElementException:
        print(f"Element not found: {action['selector']}")
    except WebDriverException as e:
        print(f"Error executing action: {e}")
    finally:
        # 프레임에서 나와 원래 컨텍스트로 전환
        if 'iframe_selector' in action:
            driver.switch_to.default_content()


if __name__ == '__main__':
    socketio.run(app, host="0.0.0.0", port=8088, debug=True)

