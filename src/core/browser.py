"""
小红书工具包浏览器驱动管理模块

负责Chrome浏览器的初始化、配置和生命周期管理
"""

import asyncio
import time
from typing import Optional, List, Dict, Any
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from .config import XHSConfig
from .exceptions import BrowserError, handle_exception
from ..utils.logger import get_logger

logger = get_logger(__name__)


class ChromeDriverManager:
    """Chrome浏览器驱动管理器"""
    
    def __init__(self, config: XHSConfig):
        """
        初始化浏览器驱动管理器
        
        Args:
            config: 配置管理器实例
        """
        self.config = config
        self.driver: Optional[webdriver.Chrome] = None
        self.is_initialized = False
    
    @handle_exception
    def _create_webrtc_prevention_extension(self) -> str:
        """
        创建一个临时的Chrome扩展来强制禁用WebRTC (Manifest V3版本)
        返回扩展的文件夹路径
        """
        import os
        import tempfile

        # 创建一个临时目录存放扩展文件
        ext_dir = os.path.join(tempfile.gettempdir(), 'xhs_webrtc_blocker_v3')
        os.makedirs(ext_dir, exist_ok=True)

        # 1. manifest.json (更新为 V3 格式)
        manifest_content = """
        {
            "name": "WebRTC Blocker V3",
            "version": "1.0",
            "manifest_version": 3,
            "permissions": ["privacy"],
            "background": {
                "service_worker": "background.js"
            }
        }
        """

        # 2. background.js (Service Worker 逻辑)
        # 直接在 Service Worker 启动时应用最高级别的屏蔽策略
        background_content = """
        // 监听插件安装或浏览器启动事件
        chrome.runtime.onInstalled.addListener(() => {
            applyWebRTCProtection();
        });

        chrome.runtime.onStartup.addListener(() => {
            applyWebRTCProtection();
        });

        // 立即执行一次以防万一
        applyWebRTCProtection();

        function applyWebRTCProtection() {
            // disable_non_proxied_udp: 禁止非代理的 UDP 流量
            // 这是配合 SOCKS5 代理使用的最安全模式
            chrome.privacy.network.webRTCIPHandlingPolicy.set({
                value: "disable_non_proxied_udp"
            }, () => {
                if (chrome.runtime.lastError) {
                    console.error("WebRTC Policy Error:", chrome.runtime.lastError);
                } else {
                    console.log("🛡️ WebRTC Blocker: Policy set to disable_non_proxied_udp");
                }
            });
        }
        """

        # 写入文件
        try:
            with open(os.path.join(ext_dir, 'manifest.json'), 'w', encoding='utf-8') as f:
                f.write(manifest_content)
                
            with open(os.path.join(ext_dir, 'background.js'), 'w', encoding='utf-8') as f:
                f.write(background_content)
                
            logger.info(f"🛡️ WebRTC V3 屏蔽插件已生成: {ext_dir}")
            return ext_dir
            
        except Exception as e:
            logger.error(f"生成WebRTC插件失败: {e}")
            raise e

    @handle_exception
    def create_driver(self) -> webdriver.Chrome:
        """
        创建Chrome浏览器驱动
        
        Returns:
            Chrome WebDriver实例
            
        Raises:
            BrowserError: 当创建驱动失败时
        """
        logger.info("🚀 初始化Chrome浏览器驱动...")
        
        try:
            if self.driver:
                logger.debug("检测到现有驱动实例，先关闭")
                self.close_driver()
            
            # 设置Chrome选项
            chrome_options = self._create_chrome_options()
            
            # 创建驱动
            if self.config.enable_remote_browser:
                debugger_address = f"{self.config.remote_browser_host}:{self.config.remote_browser_port}/wd/hub"
                logger.info(f"🌐 连接到远程浏览器: {debugger_address}")
                logger.debug("远程浏览器连接选项配置完成")
                self.driver = webdriver.Remote(command_executor=debugger_address, options=chrome_options)
            else:
                # 设置Chrome服务
                service = self._create_chrome_service()
                self.driver = webdriver.Chrome(service=service, options=chrome_options)
            
            self.is_initialized = True
            
            logger.info("✅ Chrome浏览器驱动初始化成功")
            logger.debug(f"Chrome版本: {self.driver.capabilities['browserVersion']}")
            logger.debug(f"ChromeDriver版本: {self.driver.capabilities['chrome']['chromedriverVersion']}")
            
            return self.driver
            
        except Exception as e:
            raise BrowserError(f"创建Chrome驱动失败: {str(e)}", browser_action="create_driver") from e

    def _create_chrome_options(self) -> Options:
        """创建Chrome选项"""
        chrome_options = Options()
        
        # 本地浏览器启动配置
        logger.info("🖥️ 启用本地浏览器模式")

        chrome_options.add_argument('--proxy-bypass-list=<-loopback>')
        
        # 基础选项
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        # chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--disable-software-rasterizer')
        chrome_options.add_argument('--disable-background-timer-throttling')
        chrome_options.add_argument('--disable-backgrounding-occluded-windows')
        chrome_options.add_argument('--disable-renderer-backgrounding')
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36')
        
        # 禁用自动化扩展
        chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        # 无头模式配置
        if self.config.headless:
            # 强制无头模式 - 双重保险
            chrome_options.add_argument('--headless=new')  # 新版Chrome支持
            chrome_options.add_argument('--headless')      # 传统支持
            
            # Windows环境GPU禁用（必需）
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--disable-gpu-compositing')
            
            # 强制无界面运行
            chrome_options.add_argument('--no-first-run')
            chrome_options.add_argument('--disable-default-apps')
            chrome_options.add_argument('--disable-infobars')
            chrome_options.add_argument('--disable-extensions')
            chrome_options.add_argument('--disable-popup-blocking')
            
            # 隐藏UI元素
            chrome_options.add_argument('--hide-scrollbars')
            chrome_options.add_argument('--mute-audio')
            chrome_options.add_argument('--disable-notifications')
            chrome_options.add_argument('--disable-features=TranslateUI')
            
            # 添加调试端口（有助于无头模式稳定性）
            chrome_options.add_argument('--remote-debugging-port=9222')
            
            # 窗口设置（即使无头模式也设置）
            chrome_options.add_argument('--start-maximized')

            logger.info("🔒 启用强制无头浏览器模式（双重保险）")
        
        # 设置Chrome可执行文件路径
        if self.config.chrome_path:
            chrome_options.binary_location = self.config.chrome_path
            logger.debug(f"使用Chrome路径: {self.config.chrome_path}")
        
        # 禁用WebRTC
        chrome_options.add_argument('--disable-webrtc')
        
        # 禁用密码保存提示
        chrome_options.add_experimental_option("prefs", {
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False
        })
        
        # 禁用图片加载以加快速度（可选）
        if self.config.disable_images:
            chrome_options.add_experimental_option("prefs", {
                "profile.managed_default_content_settings.images": 2
            })
            logger.debug("已禁用图片加载")
        
        # 窗口大小
        chrome_options.add_argument('--window-size=1920,1080')

        # 根据操作系统设置 user-data-dir
        import os
        import tempfile
        if os.name == "nt":  # Windows
            chrome_options.add_argument(
                r"--user-data-dir=C:\Users\DELL\AppData\Local\Google\Chrome for Testing\User Data"
            )
        else:  # Linux / Docker
            # 使用临时目录，避免卷冲突和权限问题
            tmp_user_data_dir = tempfile.mkdtemp()
            chrome_options.add_argument(f"--user-data-dir={tmp_user_data_dir}")

        # 调试选项
        if self.config.debug_mode:
            chrome_options.add_argument('--enable-logging')
            chrome_options.add_argument('--log-level=0')
            logger.debug("已启用Chrome调试日志")

        # 配置代理
        if self.config.proxy and self.config.local_proxy:
            local_proxy = self.config.local_proxy
            remote_proxy = self.config.proxy
            if local_proxy:
                logger.info(f"🛡️ 启用代理配置: {local_proxy} (remote: {remote_proxy})")
                # Chrome 接受的格式: --proxy-server=socks5://127.0.0.1:1080
                chrome_options.add_argument(f'--proxy-server={local_proxy}')

        # 隐藏自动化特征
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option('excludeSwitches', ['enable-automation'])

        # --- [新增] 加载防WebRTC泄漏 ---
        try:
            webrtc_ext_path = self._create_webrtc_prevention_extension()
            chrome_options.add_argument(f'--load-extension={webrtc_ext_path}')
            logger.info("🛡️ 已加载 WebRTC 屏蔽插件")
        except Exception as e:
            logger.error(f"无法加载WebRTC插件: {e}")

        # --- [保留] 双重保险：继续保留之前的 Prefs 设置 ---
        # 即使有了插件，这些设置也建议保留，作为兜底
        preferences = {
            "webrtc.ip_handling_policy": "disable_non_proxied_udp",
            "webrtc.multiple_routes_enabled": False,
            "webrtc.nonproxied_udp_enabled": False,
            "profile.password_manager_enabled": False
        }
        chrome_options.add_experimental_option("prefs", preferences)

        # --- [新增] 强力静音模式 ---
        # 设置日志级别为 3 (FATAL)，只有极其严重的崩溃才会打印
        chrome_options.add_argument('--log-level=3')
        chrome_options.add_argument('--silent')
        
        # 移除控制台多余输出
        chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
        
        logger.debug("本地浏览器选项配置完成")
        return chrome_options
    
    def _create_chrome_service(self) -> Service:
        """创建Chrome服务"""
        service_args = []
        # 设置ChromeDriver路径
        chromedriver_path = self.config.chromedriver_path
        if chromedriver_path:
            logger.debug(f"使用ChromeDriver路径: {chromedriver_path}")
            service = Service(executable_path=chromedriver_path, service_args=service_args)
        else:
            logger.debug("使用系统PATH中的ChromeDriver")
            service = Service(service_args=service_args)
        
        return service
    
    @handle_exception
    def navigate_to_creator_center(self) -> None:
        """
        导航到小红书创作者中心
        
        Raises:
            BrowserError: 当导航失败时
        """
        if not self.driver:
            raise BrowserError("浏览器驱动未初始化", browser_action="navigate")
        
        try:
            logger.info("🌐 导航到小红书创作者中心...")
            creator_url = "https://creator.xiaohongshu.com/"
            
            self.driver.get(creator_url)
            time.sleep(2)  # 等待页面加载
            
            current_url = self.driver.current_url
            logger.debug(f"当前URL: {current_url}")
            
            if "creator.xiaohongshu.com" in current_url:
                logger.info("✅ 成功访问创作者中心")
            else:
                logger.warning(f"⚠️ 可能未成功进入创作者中心，当前URL: {current_url}")
                
        except Exception as e:
            raise BrowserError(f"导航到创作者中心失败: {str(e)}", browser_action="navigate") from e
    
    @handle_exception
    def load_cookies(self, cookies: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        加载cookies到浏览器
        
        Args:
            cookies: Cookie列表
            
        Returns:
            加载结果信息
            
        Raises:
            BrowserError: 当加载cookies失败时
        """
        if not self.driver:
            raise BrowserError("浏览器驱动未初始化", browser_action="load_cookies")
        
        try:
            logger.info(f"🍪 开始加载 {len(cookies)} 个cookies...")
            
            success_count = 0
            error_count = 0
            
            for cookie in cookies:
                try:
                    # 确保cookie有必需的字段
                    cookie_data = {
                        'name': cookie['name'],
                        'value': cookie['value'],
                        'domain': cookie.get('domain', '.xiaohongshu.com'),
                        'path': cookie.get('path', '/'),
                        'secure': cookie.get('secure', False)
                    }
                    
                    # 只添加过期时间如果存在且有效
                    if 'expiry' in cookie and cookie['expiry']:
                        cookie_data['expiry'] = int(cookie['expiry'])
                    
                    self.driver.add_cookie(cookie_data)
                    success_count += 1
                    
                except Exception as cookie_error:
                    logger.debug(f"加载cookie失败 ({cookie.get('name', 'unknown')}): {cookie_error}")
                    error_count += 1
            
            logger.info(f"✅ Cookies加载完成: 成功 {success_count}, 失败 {error_count}")
            
            # 刷新页面应用cookies
            self.driver.refresh()
            time.sleep(2)
            
            return {
                "success_count": success_count,
                "error_count": error_count,
                "total_count": len(cookies)
            }
            
        except Exception as e:
            raise BrowserError(f"加载cookies失败: {str(e)}", browser_action="load_cookies") from e
    
    @handle_exception
    def take_screenshot(self, filename: str = "screenshot.png") -> str:
        """
        截取当前页面截图
        
        Args:
            filename: 截图文件名
            
        Returns:
            截图文件路径
            
        Raises:
            BrowserError: 当截图失败时
        """
        if not self.driver:
            raise BrowserError("浏览器驱动未初始化", browser_action="screenshot")
        
        try:
            logger.debug(f"📸 正在截图: {filename}")
            screenshot_path = self.driver.save_screenshot(filename)
            logger.debug(f"✅ 截图已保存: {filename}")
            return filename
            
        except Exception as e:
            raise BrowserError(f"截图失败: {str(e)}", browser_action="screenshot") from e
    
    @handle_exception
    def wait_for_element(self, selector: str, timeout: int = 10, by: str = "css") -> Any:
        """
        等待元素出现
        
        Args:
            selector: 元素选择器
            timeout: 超时时间（秒）
            by: 定位方式（css, xpath, id等）
            
        Returns:
            找到的元素
            
        Raises:
            BrowserError: 当元素未找到时
        """
        if not self.driver:
            raise BrowserError("浏览器驱动未初始化", browser_action="wait_element")
        
        try:
            wait = WebDriverWait(self.driver, timeout)
            
            by_map = {
                "css": By.CSS_SELECTOR,
                "xpath": By.XPATH,
                "id": By.ID,
                "class": By.CLASS_NAME,
                "tag": By.TAG_NAME
            }
            
            by_method = by_map.get(by, By.CSS_SELECTOR)
            element = wait.until(EC.presence_of_element_located((by_method, selector)))
            
            logger.debug(f"✅ 元素已找到: {selector}")
            return element
            
        except TimeoutException:
            raise BrowserError(f"等待元素超时: {selector}", browser_action="wait_element")
        except Exception as e:
            raise BrowserError(f"等待元素失败: {str(e)}", browser_action="wait_element") from e
    
    def close_driver(self) -> None:
        """关闭浏览器驱动"""
        if self.driver:
            try:
                logger.debug("🔒 正在关闭浏览器驱动...")
                self.driver.quit()
                logger.debug("✅ 浏览器驱动已关闭")
            except Exception as e:
                logger.warning(f"⚠️ 关闭浏览器驱动时出错: {e}")
            finally:
                self.driver = None
                self.is_initialized = False
    
    def __enter__(self):
        """上下文管理器入口"""
        return self.create_driver()
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close_driver()
    
    def __del__(self):
        """析构函数，确保驱动被关闭"""
        self.close_driver()


# 便捷函数
def create_browser_manager(config: XHSConfig) -> ChromeDriverManager:
    """
    创建浏览器管理器的便捷函数
    
    Args:
        config: 配置管理器实例
        
    Returns:
        浏览器管理器实例
    """
    return ChromeDriverManager(config) 
