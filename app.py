import difflib
import json
import re
import logging
from collections import Counter, defaultdict
import pandas as pd
from transliterate import translit
from flask import Flask, render_template, request, redirect, send_file, make_response, flash
from werkzeug.utils import secure_filename
import os
from rapidfuzz import fuzz
from rapidfuzz.fuzz import ratio
import matplotlib.pyplot as plt
from openpyxl import load_workbook, Workbook
from openpyxl.drawing.image import Image as ExcelImage
from datetime import datetime
from tkinter import filedialog
import requests
import vk_api
import io


#http://127.0.0.1:5000/classify
#python -m venv venv
#venv\Scripts\activate
#pip install -r requirements.txt
#python app.py 
#vk1.a.EV012Jg5bDLAsb0ctsMzay2CBgzLLJYNhd6AHEKsEO_mjK-qGMZCIjHR3b4QtKih7JMXyfbfnakDdq2euVPdcGwJ4zEdhd777ogPIc2-BZl_5HiBZRPRiNbZjJYr1EM9CVoFLZ9iZDUhdF7o6R5tR_p9NpylxISHkHmrxbotOaVNGZBr_dzcDEziKIr3WjOzzgJqIQ3t2AA0ZyqcAhsm_Q


app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max
app.secret_key = 'secret-key-123'  # Для flash сообщений

UPLOAD_FOLDER = app.config['UPLOAD_FOLDER']
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

VK_ACCESS_TOKEN = "vk1.a.C9lxByV1hk11ZBOLChPKunViUZQNycg3o4IQOOY5JiU8d7nTFoSgkkWQz96ky9xlkJ7som-Ui67Woeyi2pioYNUrgUS31USnOFostoQ96ipG8tCyw78sXqPcwFQ20euLDf3cWVU2Qsa-5sPhm9DlsbVVBcmykzrcmtQPmQCxG-KeKHUREZVOLE6GLl0Jn_IQS5idi3SUIiX-bPo63cYIyA"  
VK_API_VERSION = "5.131"
count = 1000
offset = 0
all_users = []

# Настройка логгирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== РОУТЫ ==========
@app.route('/test_download')
def test_download():
    try:
        # Создаем тестовый файл
        test_data = pd.DataFrame({'Column1': [1, 2], 'Column2': ['A', 'B']})
        test_path = os.path.join(UPLOAD_FOLDER, 'test_file.xlsx')
        test_data.to_excel(test_path, index=False)
        
        return send_file(
            test_path,
            as_attachment=True,
            download_name='test_file.xlsx',
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        return f"Ошибка: {str(e)}"

@app.route('/')
def landing():
    """Лендинговая страница"""
    response = make_response(render_template('landing.html'))
    response.headers['Cache-Control'] = 'no-store'
    return response

@app.route('/app')
def app_home():
    """Главная страница приложения"""
    response = make_response(render_template('index.html'))
    return response

@app.route('/app/download_subscribers', methods=['POST'])
def download_subscribers():
    try:
        group_id = request.form.get('group_id')
        if not group_id:
            flash("Пожалуйста, введите ID или короткое имя группы.", 'error')
            return redirect('/app')

        logger.info(f"Начало обработки запроса для группы {group_id}")
        
        all_users = get_vk_group_members(group_id)
        
        if isinstance(all_users, str):
            logger.error(f"Ошибка VK API: {all_users}")
            flash(all_users, 'error')
            return redirect('/app')

        if not all_users:
            flash("Не удалось получить подписчиков или группа пуста", 'warning')
            return redirect('/app')

        # Создаем DataFrame
        data = [{
            "ID": user.get("id", ""),
            "Фамилия": user.get("last_name", ""),
            "Имя": user.get("first_name", ""),
            "Дата рождения": user.get("bdate", "")
        } for user in all_users]

        df = pd.DataFrame(data)
        
        # Создаем файл в памяти
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        
        output.seek(0)
        filename = f"subscribers_{group_id}_{datetime.now().strftime('%Y%m%d')}.xlsx"
        
        logger.info(f"Файл {filename} успешно сформирован")
        
        return send_file(
            output,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        
    except Exception as e:
        logger.error(f"Критическая ошибка: {str(e)}", exc_info=True)
        flash(f"Произошла ошибка: {str(e)}", 'error')
        return redirect('/app')

@app.route('/app/categories', methods=['GET', 'POST'])
def download_by_categories():
    """Фильтрация подписчиков по категориям"""
    if request.method == 'GET':
        return render_template('categories.html')

    try:
        # Получаем параметры фильтрации
        group_id = request.form['group_id']
        age_range = request.form.get('age_range')
        exact_age = request.form.get('exact_age')
        include_location = 'include_location' in request.form
        include_education = 'include_education' in request.form
        include_career = 'include_career' in request.form
        include_interests = 'include_interests' in request.form

        members = get_vk_group_members_with_details(group_id)
        filtered = filter_members(
            members,
            age_range,
            exact_age,
            include_location,
            include_education,
            include_career,
            include_interests
        )

        filename = f"filtered_subscribers_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        return send_excel_file(filtered, filename)
    except Exception as e:
        logger.error(f"Ошибка в download_by_categories: {str(e)}")
        flash(f"Произошла ошибка: {str(e)}", 'error')
        return redirect('/app/categories')

@app.route('/app/classify', methods=['GET', 'POST'])
def classify():
    """Классификация подписчиков"""
    if request.method == 'GET':
        return render_template('classify.html')

    try:
        # Проверка наличия файла подписчиков
        subscribers_file = request.files.get('subscribers')
        if not subscribers_file or subscribers_file.filename == '':
            flash('Пожалуйста, загрузите файл с подписчиками', 'error')
            return redirect(request.url)

        # Проверка формата файла подписчиков
        if not allowed_file(subscribers_file.filename):
            flash('Файл подписчиков должен быть в формате Excel (.xlsx, .xls)', 'error')
            return redirect(request.url)

        # Сохранение файла подписчиков
        subscribers_path = save_uploaded_file(subscribers_file)
        logger.info(f"Файл подписчиков сохранен: {subscribers_path}")

        # Обработка файлов групп
        uploaded_files = []
        labels = []
        
        for i in range(1, 3):  # Обрабатываем до 2 групп
            file = request.files.get(f'group{i}')
            label = request.form.get(f'label{i}', '').strip()

            if file and file.filename and label:
                if not allowed_file(file.filename):
                    flash(f'Файл группы {i} должен быть в формате Excel (.xlsx, .xls)', 'error')
                    continue
                
                path = save_uploaded_file(file)
                uploaded_files.append(path)
                labels.append(label)
                logger.info(f"Файл группы {i} сохранен: {path} с меткой '{label}'")

        # Проверка, что загружены файлы групп
        if not uploaded_files:
            flash('Пожалуйста, загрузите хотя бы один файл группы с меткой', 'error')
            return redirect(request.url)

        # Классификация пользователей
        try:
            result_df = classify_users(subscribers_path, uploaded_files, labels)
            logger.info("Классификация завершена успешно")
        except Exception as e:
            logger.error(f"Ошибка классификации: {str(e)}")
            flash(f'Ошибка при классификации: {str(e)}', 'error')
            return redirect(request.url)

        # Сохранение результата
        filename = f"classified_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        result_path = os.path.join(UPLOAD_FOLDER, filename)
        
        try:
            save_with_summary(result_df, result_path)
            logger.info(f"Результат сохранен: {result_path}")
        except Exception as e:
            logger.error(f"Ошибка при сохранении результата: {str(e)}")
            flash('Ошибка при создании результата', 'error')
            return redirect(request.url)

        # Отправка файла
        try:
            response = send_file(
                result_path,
                as_attachment=True,
                download_name=filename,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            
            # Удаляем временные файлы после отправки
            cleanup_files([subscribers_path] + uploaded_files + [result_path])
            
            return response
        except Exception as e:
            logger.error(f"Ошибка при отправке файла: {str(e)}")
            flash('Ошибка при отправке файла', 'error')
            return redirect(request.url)

    except Exception as e:
        logger.error(f"Общая ошибка: {str(e)}")
        flash('Произошла ошибка при обработке запроса', 'error')
        return redirect(request.url)

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

def allowed_file(filename):
    """Проверка разрешенных расширений файлов"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in {'xlsx', 'xls'}

def save_uploaded_file(file):
    """Безопасное сохранение загруженного файла"""
    filename = secure_filename(file.filename)
    path = os.path.join(UPLOAD_FOLDER, filename)
    
    try:
        file.save(path)
        if not os.path.exists(path):
            raise Exception(f"Файл не был сохранен: {path}")
        return path
    except Exception as e:
        logger.error(f"Ошибка сохранения файла {filename}: {str(e)}")
        raise Exception(f"Не удалось сохранить файл {filename}")

def cleanup_files(file_paths):
    """Удаление временных файлов"""
    for path in file_paths:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            logger.warning(f"Не удалось удалить файл {path}: {str(e)}")

def get_vk_group_members(group_id, count=1000):
    """Получение списка участников группы"""
    all_users = []
    offset = 0
    
    while True:
        url = "https://api.vk.com/method/groups.getMembers"
        params = {
            "access_token": VK_ACCESS_TOKEN,
            "v": VK_API_VERSION,
            "group_id": group_id,
            "fields": "first_name,last_name,bdate",
            "count": count,
            "offset": offset
        }

        res = requests.get(url, params=params).json()
        if "error" in res:
            return f"Ошибка VK API: {res['error'].get('error_msg', 'Неизвестная ошибка')}"

        members = res["response"]["items"]
        all_users.extend(members)
        offset += count

        if offset >= res["response"]["count"]:
            break
            
    return all_users

def get_vk_group_members_with_details(group_id, count=1000):
    """Получение участников с расширенной информацией"""
    vk_session = vk_api.VkApi(token=VK_ACCESS_TOKEN)
    vk = vk_session.get_api()
    
    members = []
    offset = 0
    
    while True:
        response = vk.groups.getMembers(
            group_id=group_id,
            fields="bdate,city,home_town,career,universities,interests",
            offset=offset,
            count=count,
            v=VK_API_VERSION
        )
        members.extend(response['items'])
        offset += count
        if offset >= response['count']:
            break
            
    return members

def filter_members(members, age_range=None, exact_age=None, 
                  include_location=False, include_education=False, 
                  include_career=False, include_interests=False):
    """Фильтрация участников по заданным критериям"""
    today = datetime.today()
    filtered = []
    
    if include_interests:
        keywords_map = load_interest_keywords()

    for user in members:
        user_data = process_user_basic_info(user)
        age = calculate_age(user.get("bdate"), today)
        
        if not filter_by_age(age, age_range, exact_age):
            continue
            
        user_data = process_additional_info(
            user_data, user, age,
            include_location,
            include_education,
            include_career,
            include_interests,
            keywords_map if include_interests else None
        )
        
        filtered.append(user_data)
        
    return filtered

def process_user_basic_info(user):
    """Обработка базовой информации о пользователе"""
    return {
        "ID": user['id'],
        "Имя": user.get("first_name", ""),
        "Фамилия": user.get("last_name", "")
    }

def calculate_age(bdate, today):
    """Вычисление возраста по дате рождения"""
    if not bdate or len(bdate.split('.')) != 3:
        return None
        
    try:
        bdate_obj = datetime.strptime(bdate, "%d.%m.%Y")
        return today.year - bdate_obj.year - ((today.month, today.day) < (bdate_obj.month, bdate_obj.day))
    except ValueError:
        return None

def filter_by_age(age, age_range, exact_age):
    """Фильтрация по возрасту"""
    if exact_age:
        return age and age == int(exact_age)
    elif age_range:
        try:
            a, b = map(int, age_range.split('-'))
            return age and (a <= age <= b)
        except:
            return False
    return True

def process_additional_info(user_data, user, age, 
                          include_location, include_education,
                          include_career, include_interests, keywords_map):
    """Обработка дополнительной информации о пользователе"""
    user_data["Возраст"] = age if age is not None else ""
    
    if include_location:
        user_data.update(get_location_info(user))
        
    if include_education:
        user_data.update(get_education_info(user))
        
    if include_career:
        user_data.update(get_career_info(user))
        
    if include_interests:
        user_data["Интересы"] = get_interests_info(user, keywords_map)
        
    return user_data

def get_location_info(user):
    """Получение информации о местоположении"""
    return {
        "Родной город": user.get("home_town", ""),
        "Город 'Контакты'": user.get("city", {}).get("title", ""),
        "Город 'Карьера'": user.get("career", [{}])[0].get("city_name", "") if user.get("career") else ""
    }

def get_education_info(user):
    """Получение информации об образовании"""
    unis = user.get("universities", [])
    if unis:
        uni = unis[0]
        return {
            "Вуз": uni.get("name", ""),
            "Факультет": uni.get("faculty_name", ""),
            "Год выпуска": uni.get("graduation", "")
        }
    return {
        "Вуз": "",
        "Факультет": "",
        "Год выпуска": ""
    }

def get_career_info(user):
    """Получение информации о карьере"""
    careers = user.get("career", [])
    if careers:
        job = careers[0]
        return {
            "Место работы": job.get("company", ""),
            "Должность": job.get("position", ""),
            "Год начала": job.get("from", ""),
            "Год окончания": job.get("until", "")
        }
    return {
        "Место работы": "",
        "Должность": "",
        "Год начала": "",
        "Год окончания": ""
    }

def get_interests_info(user, keywords_map):
    """Анализ интересов пользователя"""
    profile_interests = analyze_profile_field_interests(user, keywords_map)
    group_interests = analyze_user_interests(user['id'], keywords_map)
    combined = Counter(profile_interests) + group_interests
    return ", ".join([cat for cat, _ in combined.most_common(3)])

def analyze_user_interests(user_id, keywords_map):
    """Анализ интересов по группам пользователя"""
    interests_counter = Counter()
    try:
        vk_session = vk_api.VkApi(token=VK_ACCESS_TOKEN)
        vk = vk_session.get_api()
        groups = vk.groups.get(user_id=user_id, extended=1, fields="description,activity", v=VK_API_VERSION)["items"]
        for group in groups:
            fields_to_check = [group.get("name", ""), group.get("description", ""), group.get("activity", "")]
            for field in fields_to_check:
                matched_categories = extract_interests_from_text(field, keywords_map)
                for cat in matched_categories:
                    interests_counter[cat] += 1
    except Exception:
        pass
    return interests_counter

def analyze_profile_field_interests(user_profile, keywords_map):
    """Анализ поля 'Интересы' в профиле"""
    field_text = user_profile.get("interests", "")
    return extract_interests_from_text(field_text, keywords_map)

def send_excel_file(data, filename):
    """Создание и отправка Excel файла"""
    wb = Workbook()
    ws = wb.active
    if data:
        ws.append(list(data[0].keys()))
        for item in data:
            ws.append(list(item.values()))
    
    file_stream = io.BytesIO()
    wb.save(file_stream)
    file_stream.seek(0)
    
    return send_file(
        file_stream,
        as_attachment=True,
        download_name=filename,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

def load_interest_keywords():
    """Загрузка ключевых слов для категорий интересов"""
    try:
        with open("interests_keywords.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка загрузки файла интересов: {str(e)}")
        return {}

# ========== ФУНКЦИИ КЛАССИФИКАЦИИ ==========

def classify_users(subscribers_path, group_paths, group_labels):
    """Классификация пользователей по группам"""
    subscribers = pd.read_excel(subscribers_path)
    subscribers["Категория"] = ""
    subscribers["Уверенность"] = 0

    name_cache = {}
    surname_cache = {}

    for group_path, label in zip(group_paths, group_labels):
        group = pd.read_excel(group_path)
        group["Имя_норм"] = group["Имя"].map(lambda x: normalize_name(x))
        group["Фамилия_норм"] = group["Фамилия"].map(lambda x: normalize(x))
        group["Дата_дм"] = group["Дата рождения"].map(extract_day_month)
        group["Дата_полная"] = group["Дата рождения"].map(extract_full_date)

        group_dict = defaultdict(list)
        for _, row in group.iterrows():
            group_dict[(row["Имя_норм"], row["Фамилия_норм"])].append(row)

        for i, sub in subscribers.iterrows():
            process_subscriber(subscribers, i, sub, group_dict, label, name_cache, surname_cache)

    return subscribers

def process_subscriber(subscribers, index, sub, group_dict, label, name_cache, surname_cache):
    """Обработка одного подписчика для классификации"""
    sub_name = name_cache.setdefault(sub["Имя"], normalize_name(sub["Имя"]))
    sub_surname = surname_cache.setdefault(sub["Фамилия"], normalize(sub["Фамилия"]))
    sub_birth_full = extract_full_date(sub.get("Дата рождения", ""))
    sub_birth_dm = extract_day_month(sub.get("Дата рождения", ""))

    best_score = 0
    matched_row = None

    candidates = group_dict.get((sub_name, sub_surname), [])

    for row in candidates:
        birth_score = calculate_birth_score(sub_birth_full, sub_birth_dm, row)
        score = birth_score if birth_score > 0 else 0.7

        if score > best_score:
            best_score = score
            matched_row = row

    if best_score >= 0.7:
        update_subscriber_info(subscribers, index, label, best_score, matched_row)

def calculate_birth_score(sub_birth_full, sub_birth_dm, row):
    """Вычисление оценки совпадения по дате рождения"""
    if sub_birth_full and row["Дата_полная"] == sub_birth_full:
        return 1.0
    elif sub_birth_dm and row["Дата_дм"] == sub_birth_dm:
        return 0.9
    return 0

def update_subscriber_info(subscribers, index, label, score, matched_row):
    """Обновление информации о подписчике"""
    subscribers.at[index, "Категория"] = label
    subscribers.at[index, "Уверенность"] = round(score * 100)

    if matched_row is not None:
        for col in matched_row.index:
            if col not in ["Имя", "Фамилия", "Дата рождения", "Имя_норм", "Фамилия_норм", "Дата_дм", "Дата_полная"]:
                subscribers.at[index, col] = matched_row[col]

# ========== ФУНКЦИИ ОБРАБОТКИ ТЕКСТА ==========

def normalize(text):
    """Нормализация текста"""
    if pd.isna(text):
        return ''
    return translit(str(text).strip().lower(), 'ru', reversed=True)

name_variations = {
    "саша": "александр", "сашка": "александр", "шура": "александр",
    "саня": "александр", "санечка": "александр", "сашаа": "александр",
    "лена": "елена", "лёна": "елена", "еленка": "елена",
    "настя": "анастасия", "наста": "анастасия", "настюша": "анастасия",
    "дениска": "денис", "дэн": "денис",
    "игорь": "игорь", "igor": "игорь"
}

def normalize_name(name):
    """Нормализация имени с учетом вариаций"""
    norm = normalize(name)
    return name_variations.get(norm, norm)

def extract_interests_from_text(text, keywords_map):
    """Извлечение категорий интересов из текста"""
    if not isinstance(text, str):
        return []
        
    text = text.lower()
    result = []
    for category, keywords in keywords_map.items():
        for word in keywords:
            if re.search(r'\b' + re.escape(word) + r'\b', text):
                result.append(category)
    return result

# ========== ФУНКЦИИ ОБРАБОТКИ ДАТ ==========

def parse_date_safe(value):
    """Безопасный парсинг даты"""
    if pd.isna(value):
        return None
    if isinstance(value, datetime):
        return value
    try:
        return pd.to_datetime(str(value), dayfirst=True, errors='coerce')
    except:
        return None

def extract_day_month(date_val):
    """Извлечение дня и месяца из даты"""
    dt = parse_date_safe(date_val)
    if pd.notna(dt):
        return dt.strftime('%d.%m')
    return ""

def extract_full_date(date_val):
    """Извлечение полной даты"""
    dt = parse_date_safe(date_val)
    if pd.notna(dt):
        return dt.strftime('%d.%m.%Y')
    return ""

# ========== СОХРАНЕНИЕ РЕЗУЛЬТАТОВ ==========

def save_with_summary(df, path):
    """Сохранение с итоговой статистикой без диаграммы"""
    try:
        # Сохраняем основной DataFrame
        df.to_excel(path, index=False)

        # Создаем сводку
        summary = df["Категория"].value_counts(dropna=False).to_dict()
        total = len(df)
        summary_data = {
            "Категория": [],
            "Количество": [],
            "Процент": []
        }

        for category, count in summary.items():
            category = category if category else "Не определено"
            summary_data["Категория"].append(category)
            summary_data["Количество"].append(count)
            summary_data["Процент"].append(round(count / total * 100, 2))

        # Сохраняем сводку без диаграммы
        with pd.ExcelWriter(path, engine='openpyxl', mode='a') as writer:
            pd.DataFrame(summary_data).to_excel(writer, sheet_name="Сводка", index=False)
            
    except Exception as e:
        logger.error(f"Ошибка при сохранении с сводкой: {str(e)}")
        raise

if __name__ == '__main__':
    app.run(debug=True)
