import sqlite3
from flask import Flask, render_template, request, redirect, url_for, g, flash, jsonify
from werkzeug.utils import secure_filename
import os
import logging # logging 모듈 임포트

app = Flask(__name__)
app.secret_key = 'your_very_secret_key_here' # 실제 배포 시에는 더 복잡하고 안전한 키를 사용하세요.

# 로깅 설정 (Render.com에서 로그를 더 잘 볼 수 있도록)
app.logger.setLevel(logging.INFO)

# 파일 업로드 설정
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'doc', 'docx', 'txt'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# 데이터베이스 연결
def get_db_connection():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

# 데이터베이스 초기화
def init_db():
    conn = get_db_connection()
    with app.open_resource('schema.sql', mode='r') as f:
        conn.cursor().executescript(f.read())
    conn.commit()
    conn.close()

# 모든 게시판 가져오기 (모든 라우트에서 사용 가능하도록 g 객체에 저장)
@app.before_request
def load_boards():
    conn = get_db_connection()
    g.boards = conn.execute('SELECT * FROM boards ORDER BY created DESC').fetchall()
    conn.close()

# 메인 페이지 - 게시판 목록 표시
@app.route('/')
def index():
    return render_template('index.html')

# 특정 게시판의 게시물 목록 표시
@app.route('/board/<int:board_id>')
def board_index(board_id):
    try:
        conn = get_db_connection()
        board = conn.execute('SELECT * FROM boards WHERE id = ?', (board_id,)).fetchone()
        if board is None:
            flash('게시판을 찾을 수 없습니다!')
            return redirect(url_for('index'))

        # 공지사항 게시물과 일반 게시물을 분리하여 가져옴
        notices = conn.execute('SELECT * FROM posts WHERE board_id = ? AND is_notice = 1 ORDER BY created DESC', (board_id,)).fetchall()
        posts = conn.execute('SELECT * FROM posts WHERE board_id = ? AND is_notice = 0 ORDER BY created DESC', (board_id,)).fetchall()
        conn.close()
        return render_template('board_index.html', board=board, notices=notices, posts=posts)
    except Exception as e:
        app.logger.error(f"게시판 인덱스 로드 중 오류 발생: {e}", exc_info=True)
        flash('게시판을 불러오는 중 오류가 발생했습니다. 다시 시도해주세요.')
        return redirect(url_for('index'))

# 게시판 생성
@app.route('/boards/create', methods=('GET', 'POST'))
def create_board():
    if request.method == 'POST':
        name = request.form['name']
        if not name:
            flash('이름은 필수입니다!') # '게시판' 단어 제거
        else:
            conn = get_db_connection()
            try:
                conn.execute('INSERT INTO boards (name) VALUES (?)', (name,))
                conn.commit()
                flash(f'{name}이(가) 생성되었습니다.') # 문구 변경
                return redirect(url_for('index'))
            except sqlite3.IntegrityError:
                flash('이미 존재하는 이름입니다!') # 문구 변경
            except Exception as e:
                app.logger.error(f"게시판 생성 중 오류 발생: {e}", exc_info=True)
                flash('게시판 생성 중 오류가 발생했습니다. 다시 시도해주세요.')
            finally:
                conn.close()
    return render_template('create_board.html')

# 게시판 삭제
@app.route('/boards/delete/<int:board_id>', methods=('POST',))
def delete_board(board_id):
    app.logger.info(f"게시판 삭제 요청 수신: {request.url}, board_id: {board_id}")
    conn = get_db_connection()
    board = conn.execute('SELECT * FROM boards WHERE id = ?', (board_id,)).fetchone()

    if board is None:
        flash('게시판을 찾을 수 없습니다!')
        conn.close()
        return redirect(url_for('index'))

    conn.execute('DELETE FROM boards WHERE id = ?', (board_id,))
    conn.commit()
    conn.close()
    flash(f'{board["name"]}이(가) 성공적으로 삭제되었습니다.') # 문구 변경
    return redirect(url_for('index'))

# 게시물 조회 및 댓글 표시
@app.route('/post/<int:post_id>')
def post(post_id):
    conn = get_db_connection()
    post = conn.execute('SELECT * FROM posts WHERE id = ?', (post_id,)).fetchone()
    if post is None:
        flash('게시물을 찾을 수 없습니다!')
        return redirect(url_for('index'))
    comments = conn.execute('SELECT * FROM comments WHERE post_id = ? ORDER BY created DESC', (post_id,)).fetchall()
    conn.close()
    return render_template('post.html', post=post, comments=comments)

# 게시물 생성
@app.route('/board/<int:board_id>/create', methods=('GET', 'POST'))
def create(board_id):
    conn = get_db_connection()
    board = conn.execute('SELECT * FROM boards WHERE id = ?', (board_id,)).fetchone()
    conn.close()
    if board is None:
        flash('게시판을 찾을 수 없습니다!')
        return redirect(url_for('index'))

    if request.method == 'POST':
        app.logger.info(f"게시물 생성 요청 수신: {request.url}, 폼 데이터: {request.form}")
        title = request.form['title']
        content = request.form['content']
        author = request.form['author']
        is_notice = request.form.get('is_notice', 0, type=int)

        if not title:
            flash('제목은 필수입니다!')
        elif not author:
            flash('작성자는 필수입니다!')
        else:
            try:
                conn = get_db_connection()
                conn.execute('INSERT INTO posts (board_id, title, content, author, is_notice) VALUES (?, ?, ?, ?, ?)',
                             (board_id, title, content, author, is_notice))
                conn.commit()
                conn.close()
                flash('게시물이 성공적으로 작성되었습니다.')
                return redirect(url_for('board_index', board_id=board_id))
            except Exception as e:
                app.logger.error(f"게시물 생성 중 오류 발생: {e}", exc_info=True)
                flash('게시물 생성 중 오류가 발생했습니다. 다시 시도해주세요.')
                # 오류 발생 시에도 create 페이지로 돌아가도록 처리
                return render_template('create.html', board=board)

    return render_template('create.html', board=board)