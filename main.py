import os
import sys
import time
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from pprint import pprint
from ebooklib import epub

POST_RETRY_LIMIT = 5
FILTER = None #FILTER = "^\s*#" # Must be a vaiil regexp
ALLOW_PAYWALLED = True
PAYWALLED_ONLY = False
EMAIL = os.environ.get("SUBSTACK_EMAIL")
PASSWORD = os.environ.get("SUBSTACK_PASS")

options = webdriver.ChromeOptions();
options.add_argument('--headless');
options.add_argument('log-level=1')
driver = webdriver.Chrome(options=options)

def get_filename(s):
    s = str(s).strip().replace(' ', '_')
    return re.sub(r'(?u)[^-\w.]', '', s)

def parse_archive(url, limit=-1, filter=None):
    driver.get(url + '/archive?sort=new')
    blog_name = driver.find_element(By.XPATH, '//*[@class="topbar"]//*[@class="headline"]//span[@class="name"]').text
    last_height = driver.execute_script("return document.body.scrollHeight")
    while True:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(0.5)
        WebDriverWait(driver, 30).until(
            EC.invisibility_of_element_located((By.CLASS_NAME, "post-preview-silhouette"))
        )
        recent_height = driver.execute_script("return document.body.scrollHeight")
        print(f"scrolling screen down. last:{last_height}, " 
              f"now:{recent_height}")
        if recent_height  == last_height:
            break
        last_height = recent_height

    posts = driver.find_elements(By.CLASS_NAME, "post-preview")
    posts_parsed = []
    for post in posts[0:limit]:
        url = post.find_element(By.CLASS_NAME, "post-preview-title").get_attribute('href')
        title = post.find_element(By.CLASS_NAME, "post-preview-title").text
        if filter and not re.match(filter, title):
            continue
        try:
            post.find_element(By.CLASS_NAME, "audience-lock")
            paywalled = True
        except NoSuchElementException:
            paywalled = False
        posts_parsed.append({'url': url, 'paywalled': paywalled, 'title': title})
    pprint(posts_parsed)
    return {'blog_name': blog_name, 'posts': posts_parsed}

def parse_post(url):
    print(f'parsing {url}')
    driver.get(url)
    post = WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((By.CLASS_NAME, "single-post")) # d.find_element(By.CLASS_NAME, "single-post")
    )

    try:
        driver.find_element(By.XPATH, '//div[@class="single-post"]//div[contains(@class,"paywall")]')
        paywalled = True
    except NoSuchElementException:
        paywalled = False

    title = post.find_element(By.CLASS_NAME, "post-title").text
    try:
        subtitle = post.find_element(By.CLASS_NAME, "subtitle").text
    except NoSuchElementException:
        print('This post has no subtittle')
        subtitle = ""

    datetime = post.find_element(By.CLASS_NAME, "post-date").get_attribute('title')
    like_count = post.find_element(By.CLASS_NAME, "like-count").text
    body = post.find_element(By.CLASS_NAME, "available-content").find_element(By.CLASS_NAME, "body")
    text_list = [
        e.get_attribute('outerHTML') 
        for e 
        in body.find_elements(By.XPATH, './*[not(contains(@class,"subscribe-widget"))]')
    ]
    text_html = '\n'.join(text_list)
    # pprint((post, title, subtitle, datetime, like_count, body))
    print(f'title: {title}, paywalled: {paywalled}, likes: {like_count}')
    return {'title': title, 'subtitle': subtitle, 'date': datetime,
            'like_count': like_count, 'text_html': text_html,
            'paywalled': paywalled
           }

def sign_in(email, password=None, login_link=None):
    print(f"signing for email: {email}")
    driver.get("https://substack.com/sign-in")
    driver.find_element(By.CLASS_NAME, "substack-login__login-option").click()
    driver.find_element(By.XPATH, '//input[@name="email"]').send_keys(email)
    driver.find_element(By.XPATH, '//input[@name="password"]').send_keys(password)
    driver.find_element(By.CLASS_NAME, "substack-login__go-button").click()
    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((By.CLASS_NAME, 'homepage-nav-user-indicator')) 
    )
    print("signed in")


if __name__ == "__main__":
    if EMAIL and PASSWORD:
        sign_in(EMAIL, PASSWORD)
    archive = parse_archive(sys.argv[1], limit=-1, filter=FILTER)

    book = epub.EpubBook()
    book.set_identifier('id00000')
    book.set_title(archive['blog_name'])
    book.set_language('en')
    book.add_metadata('DC', 'description', 'generated by pkonkol/substack-to-pdf')
    book.add_metadata('DC', 'publisher', 'substack-to-pdf')

    print(len(archive['posts']))

    toc = []
    spine = []
    not_posts = []
    for i, post in enumerate(archive['posts'][::-1]):
        j = 0
        while True:
            try:
                if ALLOW_PAYWALLED or post['paywalled'] == PAYWALLED_ONLY:
                    p = parse_post(post['url'])
                break
            except TimeoutException:
                j += 1
                if j >= POST_RETRY_LIMIT:
                    break
                print(f'retrying parsing {post["url"]} for {j} time')
        if not p:
            not_posts.append(post["url"])
            continue

        chapter = epub.EpubHtml(
            title=p['title'],
            file_name = str(i) + '.' + get_filename(p['title']) + '.xhtml',
            lang='en'
        )
        chapter.content = (
            f'<h1>{p["title"]}</h1>\n'
             '<p>'
            f'<time datetime={p["date"]}> {p["date"]} </time>'
            f'<span>Likes:{p["like_count"]} </span><span> Paywalled: {p["paywalled"]}</span>'
             '</p>\n'
            f'<a href="{post["url"]}">URL: {post["url"]}</a>\n'
            f'<h2>{p["subtitle"]}</h2>\n'
        )
        chapter.content += p['text_html']
        book.add_item(chapter)
        spine.append(chapter)
        toc.append(epub.Link(str(i) + '.' + get_filename(p['title']) + '.xhtml', p['title'], ""))
    pprint(f'not posts: {not_posts}')

    book.toc = toc
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = (['nav',] + spine)
    epub.write_epub(get_filename(archive['blog_name']) + '.epub', book, {})

    driver.quit()