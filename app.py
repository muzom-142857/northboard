import sqlite3
from flask import Flask, render_template, request, redirect, url_for, g, flash, jsonify
from werkzeug.utils import secure_filename
import os

app = Flask(__name__)
app.secret_key = 'your_very_secret_key_here' # 실제 배포 시에는 더 복잡하고 안전한 키를 사용하세요.

# 파일 업로드 설정
UPLOAD_FOLDER = 'static/uploads';
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
            finally:
                conn.close()
    return render_template('create_board.html')

# 게시판 삭제
@app.route('/boards/delete/<int:board_id>', methods=('POST',))
def delete_board(board_id):
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
        title = request.form['title']
        content = request.form['content']
        author = request.form['author']
        is_notice = 1 if request.form.get('is_notice') == 'on' else 0

        if not title:
            flash('제목은 필수입니다!')
        elif not author:
            flash('작성자는 필수입니다!')
        else:
            conn = get_db_connection()
            conn.execute('INSERT INTO posts (board_id, title, content, author, is_notice) VALUES (?, ?, ?, ?, ?)',
                         (board_id, title, content, author, is_notice))
            conn.commit()
            conn.close()
            flash('게시물이 성공적으로 작성되었습니다.')
            return redirect(url_for('board_index', board_id=board_id))

    return render_template('create.html', board=board)

# 게시물 수정
@app.route('/edit/<int:post_id>', methods=('GET', 'POST'))
def edit(post_id):
    conn = get_db_connection()
    post = conn.execute('SELECT * FROM posts WHERE id = ?', (post_id,)).fetchone()
    conn.close()

    if post is None:
        flash('게시물을 찾을 수 없습니다!')
        return redirect(url_for('index'))

    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']
        is_notice = 1 if request.form.get('is_notice') == 'on' else 0

        if not title:
            flash('제목은 필수입니다!')
        else:
            conn = get_db_connection()
            conn.execute('UPDATE posts SET title = ?, content = ?, is_notice = ? WHERE id = ?',
                         (title, content, is_notice, post_id))
            conn.commit()
            conn.close()
            flash('게시물이 성공적으로 수정되었습니다.')
            return redirect(url_for('post', post_id=post_id))

    return render_template('edit.html', post=post)

# 게시물 삭제 (작성자 확인 제거)
@app.route('/delete/<int:post_id>', methods=('POST',))
def delete(post_id):
    conn = get_db_connection()
    post = conn.execute('SELECT * FROM posts WHERE id = ?', (post_id,)).fetchone()

    if post is None:
        flash('게시물을 찾을 수 없습니다!')
        conn.close()
        return redirect(url_for('index'))

    conn.execute('DELETE FROM posts WHERE id = ?', (post_id,))
    conn.commit()
    conn.close()
    flash('게시물이 성공적으로 삭제되었습니다.')
    return redirect(url_for('board_index', board_id=post['board_id']))

# 댓글 추가
@app.route('/post/<int:post_id>/comment', methods=('POST',))
def add_comment(post_id):
    author = request.form['author']
    content = request.form['content']

    if not author or not content:
        flash('작성자와 내용은 필수입니다!')
    else:
        conn = get_db_connection()
        conn.execute('INSERT INTO comments (post_id, author, content) VALUES (?, ?, ?)',
                     (post_id, author, content))
        conn.commit()
        conn.close()
    return redirect(url_for('post', post_id=post_id))

# 파일 업로드 라우트 (Summernote에서 사용)
@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        return jsonify({'location': url_for('static', filename='uploads/' + filename)}), 200
        try:
            filename = secure_filename(file.filename)
            # UPLOAD_FOLDER의 절대 경로를 사용하고, 디렉토리가 없으면 생성
            upload_path = os.path.join(app.root_path, app.config['UPLOAD_FOLDER'])
            os.makedirs(upload_path, exist_ok=True)
            file.save(os.path.join(upload_path, filename))
            # 파일이 저장된 후의 URL 반환
            return jsonify({'location': url_for('static', filename='uploads/' + filename)}), 200
        except Exception as e:
            # 파일 저장 중 오류 발생 시 클라이언트에 오류 메시지 반환
            return jsonify({'error': f'File upload failed: {str(e)}'}), 500
    return jsonify({'error': 'File type not allowed'}), 400

# 사이트 소개 페이지
@app.route('/about')
def about():
    return render_template('about.html')

if __name__ == '__main__':

    app.run(debug=True)
=======
    app.run(debug=True)
