import os
import logging
import sqlite3
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, g, flash, jsonify
from werkzeug.utils import secure_filename
from flask_compress import Compress

# .env 파일에서 환경 변수 로드
load_dotenv()

app = Flask(__name__)
Compress(app)  # 응답 압축 활성화
# 환경 변수에서 SECRET_KEY를 불러오거나, 없는 경우 기본값 사용
app.secret_key = os.getenv('SECRET_KEY', 'your_default_secret_key')

# SQLite 데이터베이스 경로
DATABASE_PATH = os.path.join(os.path.dirname(__file__), 'database.db')

# 로깅 설정
app.logger.setLevel(logging.INFO)

# 파일 업로드 설정
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'doc', 'docx', 'txt'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# 데이터베이스 연결 함수
def get_db_connection():
    """SQLite 데이터베이스에 연결합니다."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.OperationalError as e:
        app.logger.error(f"데이터베이스에 연결할 수 없습니다: {e}")
        raise

# 데이터베이스 초기화 함수 (CLI 명령으로만 사용)
def init_db():
    """schema.sql을 사용하여 데이터베이스를 초기화합니다."""
    conn = get_db_connection()
    cur = conn.cursor()
    with app.open_resource('schema.sql', mode='r') as f:
        cur.executescript(f.read())
    conn.commit()
    cur.close()
    conn.close()
    app.logger.info("데이터베이스가 초기화되었습니다.")

# 'flask init-db' CLI 명령어 정의
@app.cli.command('init-db')
def init_db_command():
    """데이터베이스를 초기화하는 Flask CLI 명령어."""
    init_db()
    print('데이터베이스가 성공적으로 초기화되었습니다.')

# 각 요청 전에 모든 게시판 목록을 로드
@app.context_processor
def inject_css_version():
    """모든 템플릿에 CSS 파일 버전을 주입하여 캐시 문제를 해결합니다."""
    try:
        # static/style.css 파일의 마지막 수정 시간을 가져옵니다.
        css_path = os.path.join(app.static_folder, 'style.css')
        timestamp = int(os.path.getmtime(css_path))
        return dict(css_version=timestamp)
    except (OSError, FileNotFoundError):
        # 파일이 없거나 오류 발생 시 기본값을 사용합니다.
        return dict(css_version='latest')

# 게시판 목록을 위한 간단한 인-메모리 캐시
board_cache = None

@app.before_request
def load_boards():
    global board_cache
    # init-db 명령어 실행 시에는 이 함수를 건너뜀
    if request.endpoint == 'static' or request.path.startswith('/uploads'):
        return
    if request.endpoint and 'init_db' in request.endpoint:
        return

    # 캐시가 비어있을 때만 데이터베이스에서 게시판 목록을 가져옴
    if board_cache is None:
        app.logger.info("게시판 목록 캐시가 비어있어 DB에서 새로고침합니다.")
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT * FROM boards ORDER BY created DESC')
        board_cache = cur.fetchall()
        cur.close()
        conn.close()
    
    # g 객체에 캐시된 목록을 저장하여 템플릿에서 사용
    g.boards = board_cache

# 메인 페이지
@app.route('/')
def index():
    return render_template('index.html')

# 소개 페이지
@app.route('/about')
def about():
    return render_template('about.html')

# 특정 게시판의 게시물 목록
@app.route('/board/<int:board_id>')
def board_index(board_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute('SELECT * FROM boards WHERE id = ?', (board_id,))
        board = cur.fetchone()
        if board is None:
            flash('게시판을 찾을 수 없습니다!')
            cur.close()
            conn.close()
            return redirect(url_for('index'))

        cur.execute('SELECT * FROM posts WHERE board_id = ? AND is_notice = 1 ORDER BY created DESC', (board_id,))
        notices = cur.fetchall()
        cur.execute('SELECT * FROM posts WHERE board_id = ? AND is_notice = 0 ORDER BY created DESC', (board_id,))
        posts = cur.fetchall()

        cur.close()
        conn.close()
        return render_template('board_index.html', board=board, notices=notices, posts=posts)
    except Exception as e:
        app.logger.error(f"게시판 인덱스 로드 중 오류: {e}", exc_info=True)
        flash('게시판을 불러오는 중 오류가 발생했습니다.')
        return redirect(url_for('index'))

# 게시판 생성
@app.route('/boards/create', methods=('GET', 'POST'))
def create_board():
    if request.method == 'POST':
        name = request.form['name']
        if not name:
            flash('이름은 필수입니다!')
        else:
            conn = None
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute('INSERT INTO boards (name) VALUES (?)', (name,))
                conn.commit()
                # 게시판 목록 캐시 초기화
                global board_cache
                board_cache = None
                flash(f"'{name}' 게시판이 생성되었습니다.")
                return redirect(url_for('index'))
            except sqlite3.IntegrityError:
                flash('이미 존재하는 이름입니다!')
            except Exception as e:
                app.logger.error(f"게시판 생성 중 오류: {e}", exc_info=True)
                flash('게시판 생성 중 오류가 발생했습니다.')
            finally:
                if conn:
                    cur.close()
                    conn.close()
    return render_template('create_board.html')

# 게시판 삭제
@app.route('/boards/delete/<int:board_id>', methods=('POST',))
def delete_board(board_id):
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT name FROM boards WHERE id = ?', (board_id,))
        board = cur.fetchone()

        if board is None:
            flash('게시판을 찾을 수 없습니다!')
        else:
            cur.execute('DELETE FROM boards WHERE id = ?', (board_id,))
            conn.commit()
            # 게시판 목록 캐시 초기화
            global board_cache
            board_cache = None
            flash(f"'{board['name']}' 게시판이 삭제되었습니다.")
    except Exception as e:
        app.logger.error(f"게시판 삭제 중 오류: {e}", exc_info=True)
        flash('게시판 삭제 중 오류가 발생했습니다.')
    finally:
        if conn:
            cur.close()
            conn.close()
    return redirect(url_for('index'))

# 게시물 조회
@app.route('/post/<int:post_id>')
def post(post_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT * FROM posts WHERE id = ?', (post_id,))
        post = cur.fetchone()
        if post is None:
            flash('게시물을 찾을 수 없습니다!')
            cur.close()
            conn.close()
            return redirect(url_for('index'))

        cur.execute('SELECT * FROM comments WHERE post_id = ? ORDER BY created DESC', (post_id,))
        comments = cur.fetchall()
        cur.close()
        conn.close()
        return render_template('post.html', post=post, comments=comments)
    except Exception as e:
        app.logger.error(f"게시물 로드 중 오류 (post_id: {post_id}): {e}", exc_info=True)
        flash('게시물을 불러오는 중 오류가 발생했습니다.')
        return redirect(url_for('index'))

# 게시물 생성
@app.route('/board/<int:board_id>/create', methods=('GET', 'POST'))
def create(board_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM boards WHERE id = ?', (board_id,))
    board = cur.fetchone()
    cur.close()
    conn.close()

    if board is None:
        flash('게시판을 찾을 수 없습니다!')
        return redirect(url_for('index'))

    if request.method == 'POST':
        # 디버깅을 위해 수신된 폼 데이터 전체를 로깅합니다.
        app.logger.info(f"Create Post - Form Data: {request.form}")
        title = request.form['title']
        content = request.form['content']
        author = request.form['author']
        is_notice = 1 if request.form.get('is_notice') == '1' else 0

        if not title or not author:
            flash('제목과 작성자는 필수입니다!')
        else:
            conn_post = None
            try:
                conn_post = get_db_connection()
                cur_post = conn_post.cursor()
                cur_post.execute('INSERT INTO posts (board_id, title, content, author, is_notice) VALUES (?, ?, ?, ?, ?)',
                                 (board_id, title, content, author, is_notice))
                conn_post.commit()
                flash('게시물이 성공적으로 작성되었습니다.')
                return redirect(url_for('board_index', board_id=board_id))
            except Exception as e:
                app.logger.error(f"게시물 생성 중 오류: {e}", exc_info=True)
                flash('게시물 생성 중 오류가 발생했습니다.')
            finally:
                if conn_post:
                    cur_post.close()
                    conn_post.close()
    return render_template('create.html', board=board)

# 게시물 수정
@app.route('/edit/<int:post_id>', methods=('GET', 'POST'))
def edit(post_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM posts WHERE id = ?', (post_id,))
    post = cur.fetchone()
    cur.close()
    conn.close()

    if post is None:
        flash('게시물을 찾을 수 없습니다!')
        return redirect(url_for('index'))

    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']
        is_notice = 1 if request.form.get('is_notice') == '1' else 0

        if not title:
            flash('제목은 필수입니다!')
        else:
            conn_edit = None
            try:
                conn_edit = get_db_connection()
                cur_edit = conn_edit.cursor()
                cur_edit.execute('UPDATE posts SET title = ?, content = ?, is_notice = ? WHERE id = ?',
                                 (title, content, is_notice, post_id))
                conn_edit.commit()
                flash('게시물이 성공적으로 수정되었습니다.')
                return redirect(url_for('post', post_id=post_id))
            except Exception as e:
                app.logger.error(f"게시물 수정 중 오류: {e}", exc_info=True)
                flash('게시물 수정 중 오류가 발생했습니다.')
            finally:
                if conn_edit:
                    cur_edit.close()
                    conn_edit.close()
    return render_template('edit.html', post=post)

# 게시물 삭제
@app.route('/delete/<int:post_id>', methods=('POST',))
def delete(post_id):
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT board_id FROM posts WHERE id = ?', (post_id,))
        post = cur.fetchone()

        if post is None:
            flash('게시물을 찾을 수 없습니다!')
            return redirect(url_for('index'))

        board_id = post['board_id']
        cur.execute('DELETE FROM posts WHERE id = ?', (post_id,))
        conn.commit()
        flash('게시물이 성공적으로 삭제되었습니다.')
        return redirect(url_for('board_index', board_id=board_id))
    except Exception as e:
        app.logger.error(f"게시물 삭제 중 오류: {e}", exc_info=True)
        flash('게시물 삭제 중 오류가 발생했습니다.')
        return redirect(url_for('index'))
    finally:
        if conn:
            cur.close()
            conn.close()

# 댓글 추가
@app.route('/add_comment/<int:post_id>', methods=('POST',))
def add_comment(post_id):
    author = request.form['author']
    content = request.form['content']

    if not author or not content:
        flash('작성자와 내용은 필수입니다!')
    else:
        conn = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute('INSERT INTO comments (post_id, author, content) VALUES (?, ?, ?)',
                         (post_id, author, content))
            conn.commit()
            flash('댓글이 성공적으로 추가되었습니다.')
        except Exception as e:
            app.logger.error(f"댓글 추가 중 오류: {e}", exc_info=True)
            flash('댓글 추가 중 오류가 발생했습니다.')
        finally:
            if conn:
                cur.close()
                conn.close()
    return redirect(url_for('post', post_id=post_id))

# 파일 업로드
@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify(error="No file part"), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify(error="No selected file"), 400
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        try:
            file.save(filepath)
            app.logger.info(f"파일 저장 경로: {filepath}")
            file_url = url_for('static', filename=f'uploads/{filename}')
            app.logger.info(f"생성된 파일 URL: {file_url}")
            return jsonify(location=file_url)
        except Exception as e:
            app.logger.error(f"파일 업로드 중 오류 발생: {e}", exc_info=True)
            return jsonify(error=f"File upload failed: {e}"), 500
    return jsonify(error="File type not allowed"), 400
