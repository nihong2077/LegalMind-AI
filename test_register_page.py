
from playwright.sync_api import sync_playwright
import time

def test_register_page():
    print("开始测试注册页面...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        # 监听控制台日志
        console_logs = []
        def console_handler(msg):
            console_logs.append(f"[{msg.type}] {msg.text}")
            print(f"控制台日志: [{msg.type}] {msg.text}")
        page.on('console', console_handler)
        
        # 监听网络请求
        network_requests = []
        def request_handler(request):
            network_requests.append({
                'url': request.url,
                'method': request.method,
                'resource_type': request.resource_type
            })
            print(f"网络请求: {request.method} {request.url}")
        page.on('request', request_handler)
        
        # 监听网络响应
        network_responses = []
        def response_handler(response):
            network_responses.append({
                'url': response.url,
                'status': response.status,
                'ok': response.ok
            })
            print(f"网络响应: {response.status} {response.url}")
        page.on('response', response_handler)
        
        try:
            # 导航到注册页面
            print("导航到注册页面...")
            page.goto('http://localhost:3000/auth/register')
            page.wait_for_load_state('networkidle')
            
            # 截图
            print("截图注册页面...")
            page.screenshot(path='/workspace/test_register_1.png', full_page=True)
            
            # 获取页面内容
            print("获取页面内容...")
            page_content = page.content()
            
            # 填写表单
            print("填写注册表单...")
            page.fill('input[name="username"]', 'testplaywright')
            page.fill('input[name="email"]', 'testplaywright@example.com')
            page.fill('input[name="password"]', 'password123')
            
            # 截图填写后的表单
            page.screenshot(path='/workspace/test_register_2.png', full_page=True)
            
            # 点击注册按钮
            print("点击注册按钮...")
            page.click('button[type="submit"]')
            
            # 等待响应
            print("等待响应...")
            time.sleep(3)
            
            # 截图结果
            page.screenshot(path='/workspace/test_register_3.png', full_page=True)
            
            # 获取页面状态
            print("获取页面状态...")
            page_title = page.title()
            page_url = page.url
            
            print(f"\n=== 测试结果 ===")
            print(f"页面标题: {page_title}")
            print(f"当前URL: {page_url}")
            
            print(f"\n=== 控制台日志 ===")
            for log in console_logs:
                print(log)
            
            print(f"\n=== 网络请求 ===")
            for req in network_requests:
                print(f"{req['method']} {req['url']}")
            
            print(f"\n=== 网络响应 ===")
            for res in network_responses:
                print(f"{res['status']} {res['url']}")
            
            # 检查是否有错误
            error_messages = page.locator('.text-red-400')
            if error_messages.count() > 0:
                print(f"\n=== 错误信息 ===")
                for i in range(error_messages.count()):
                    print(f"- {error_messages.nth(i).inner_text()}")
            
            # 检查是否成功
            success_messages = page.locator('.text-green-400')
            if success_messages.count() > 0:
                print(f"\n=== 成功信息 ===")
                for i in range(success_messages.count()):
                    print(f"- {success_messages.nth(i).inner_text()}")
            
        except Exception as e:
            print(f"\n=== 测试错误 ===")
            print(f"错误: {e}")
            page.screenshot(path='/workspace/test_register_error.png', full_page=True)
            import traceback
            traceback.print_exc()
        
        finally:
            browser.close()
            print("\n测试完成")

if __name__ == "__main__":
    test_register_page()

