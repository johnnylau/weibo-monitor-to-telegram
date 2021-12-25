import os
import sys
import time
import wget
import sqlite3
import configparser
import re
import json
from bs4 import BeautifulSoup
from requests_html import HTMLSession


class Weibo:
    status_id = -1
    root = "https://m.weibo.cn"

    def __init__(self):
        self.BASE_DIR = os.path.split(os.path.realpath(__file__))[0]
        config = configparser.ConfigParser()
        config.read(os.path.join(self.BASE_DIR, 'config.ini'), encoding='utf-8')
        self.WEIBO_ID = config.get("CONFIG", "WEIBO_ID")
        self.TELEGRAM_BOT_TOKEN = config.get("CONFIG", "TELEGRAM_BOT_TOKEN")
        self.TELEGRAM_CHAT_ID = config.get("CONFIG", "TELEGRAM_CHAT_ID")
        self.FAV_ID = config.get("CONFIG", "FAV_ID")
        self.COOKIES = config.get("CONFIG", "COOKIES")
        self.SESSION = HTMLSession()
        self.SESSION.adapters.DEFAULT_RETRIES = 5  # 增加重连次数
        self.SESSION.keep_alive = False  # 关闭多余连接
        proxy = config.get("CONFIG", "PROXY")
        self.PROXIES = {"http": proxy, "https": proxy}

    def send_telegram_message(self, text, weibo_link):
        """
        给电报发送文字消息
        """
        headers = {
            'Content-Type': 'application/json',
        }
        data = f'{{"chat_id":"{self.TELEGRAM_CHAT_ID}", "text":"{text}", "reply_markup": {{"inline_keyboard":' \
               f' [[{{"text":"🔗点击查看原微博", "url":"{weibo_link}"}}]]}}}} '
        url = f'https://api.telegram.org/bot{self.TELEGRAM_BOT_TOKEN}/sendMessage'
        try:
            self.SESSION.post(url, headers=headers, data=data.encode('utf-8'), proxies=self.PROXIES)
        except:
            print('    |-网络代理错误，请检查确认后关闭本程序重试')

    def send_telegram_photo(self, img_url):
        """
        给电报发送图片
        """
        url = f'https://api.telegram.org/bot{self.TELEGRAM_BOT_TOKEN}/sendPhoto'
        data = dict(chat_id=f"{self.TELEGRAM_CHAT_ID}&", photo=img_url)

        self.SESSION.post(url, data=data, proxies=self.PROXIES)        

    def parse_weibo(self, weibo):
        """
        检查当前微博是否已处理过，如果没处理过则发送博文以及配图到Telegram
        """
        conn = sqlite3.connect(os.path.join(self.BASE_DIR, 'db', 'weibo.db'))
        cursor = conn.cursor()

        sql = "SELECT COUNT(id) AS counts FROM weibo WHERE link = ?"
        cursor.execute(sql, (weibo['link'],))
        result = cursor.fetchone()

        if result[0] <= 0:
            self.send_telegram_message(
                '{}{}'.format(
                    f"[{len(weibo['pics'])}图] " if weibo['pics'] else '',
                    weibo['title'],
                ),
                weibo['link']
            )

            # 把图片url发送到Telegram中，可以第一时间在Telegram中收到推送
            for pic in weibo['pics']:
                self.send_telegram_photo(pic)

            # 配图发送到Telegram毕后，将配图独立保存到本地一份
            for pic in weibo['pics']:
                filename = pic[pic.rfind('/') + 1:]
                filename = os.path.join(self.BASE_DIR, 'images', filename)
                wget.download(pic, out=filename)

            sql = "INSERT INTO weibo(summary, link) VALUES(?, ?)"
            cursor.execute(sql, (
                weibo['title'],
                weibo['link'],
            ))
            conn.commit()
            conn.close()

            return True
        else:
            return False

    def test(self):
        print('* 正在检查微博ID是否配置正确')
        url = f'https://m.weibo.cn/api/container/getIndex?containerid=100505{self.WEIBO_ID}'
        try:
            weibo_name = self.SESSION.get(url).json()['data']['userInfo']['screen_name']
            print(f'【正确】当前设置的微博账户为：@{weibo_name}')
        except:
            print('【错误】请重新测试或检查微博数字ID是否正确')

        print('\n* 正在检查代理是否配置正确')
        try:
            status_code = self.SESSION.get('https://www.google.com',proxies=self.PROXIES, timeout=5).status_code
            if status_code == 200:
                print('【正确】代理配置正确，可正常访问')
            else:
                print('【错误】代理无法访问到电报服务器')
        except:
            print('【错误】代理无法访问到电报服务器')

    def get_status_id(self, scheme):
        pattern = (r"(?:https?://)?(?:www\.|m\.)?weibo\.c(?:om|n)"
               r"/(?:detail|status|\d+)/(\w+)")
        mGroup = re.match(pattern, scheme)
        self.status_id = mGroup.group(1)

    def extract(self, txt, begin, end, pos=0):
        try:
            first = txt.index(begin, pos) + len(begin)
            last = txt.index(end, first)
            return txt[first:last], last+len(end)
        except (ValueError, TypeError, AttributeError) as e:
            print(e)
            return None, pos

    def process_images_over_than_9(self):
        url = "{}/detail/{}".format(self.root, self.status_id)
        page = self.send_request(url).text
        data = self.extract(page, "var $render_data = [", "][0] || {};")[0]
        return json.loads(data)["status"] if data else None

    def process_imgs(self, item):
        pics = {}
        try:
            if 'pic_num' in item and item.get('pic_num') > 0:
                if len(item['pics']) < item['pic_num']:
                    item = self.process_images_over_than_9()
                pics = [pic['large']['url'] for pic in item['pics']]
            else:
                pics = []
        except Exception as e:
            print('解析出错'%e)
            pics = []
        finally:
            return pics

    def process_card(self, cards):
        for item in cards:
            weibo = {}
            retweet = {}
            weibo['link'] = item['scheme']
            self.get_status_id(item['scheme'])

            weibo['title'] = BeautifulSoup(item['mblog']['text'].replace('<br />', '\n'), 'html.parser').get_text()

            if 'retweeted_status' in item['mblog']:
                retweet = item['mblog']['retweeted_status']
                weibo['pics'] = self.process_imgs(retweet)
                try:
                    weibo['title'] = f"{weibo['title']}//@{retweet['user']['screen_name']}:{retweet['text']}"
                except:
                    weibo['title'] = f"{weibo['title']}//转发原文不可见，可能已被删除"
            else:
                weibo['pics'] = self.process_imgs(item['mblog'])

            self.parse_weibo(weibo)

    def run(self):
        print(time.strftime('%Y-%m-%d %H:%M:%S 执行完毕', time.localtime()))

        url = f'https://m.weibo.cn/api/container/getIndex?containerid=107603{self.WEIBO_ID}'
        favurl = f'https://m.weibo.cn/api/container/getIndex?containerid={self.FAV_ID}&page=1&openapp=0'

        try:
            weibo_items = self.SESSION.get(url).json()['data']['cards'][::-1]
            self.process_card(weibo_items)
            fav_items = self.send_request(favurl, True).json()['data']['cards'][::-1]
            self.process_card(fav_items)
        except Exception as e:
            print('    |-访问url出错了'%e)

    def send_request(self, url, enableHeaders=False):
        result = {}
        headers = {
            'Referer': f'https://m.weibo.cn/p/index?containerid={self.FAV_ID}',
            'User-Agent':
                f'Mozilla/5.0 (iPhone; CPU iPhone OS 9_1 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Version/9.0 Mobile/13B143 Safari/601.1',
            'Cookie': self.COOKIES,
            'X-Requested-With': f'XMLHttpRequest'
        }

        try:
            if enableHeaders:
                result = self.SESSION.get(url, headers=headers)
            else:
                result = self.SESSION.get(url)
        except Exception as e:
            print('    |-访问url出错了'%e)
        finally:
            return result


if __name__ == '__main__':
    weibo = Weibo()
    argv = sys.argv[1] if len(sys.argv) > 1 else ''
    if argv.lower() == 'test':
        weibo.test()
    else:
        weibo.run()
