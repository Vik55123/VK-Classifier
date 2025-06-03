@app.route('/categories', methods=['GET', 'POST'])
def download_by_categories():
    if request.method == 'GET':
        return render_template('categories.html')

    group_id = request.form['group_id']
    age_range = request.form.get('age_range')
    exact_age = request.form.get('exact_age')
    include_location = 'include_location' in request.form
    include_education = 'include_education' in request.form
    include_career = 'include_career' in request.form
    

    # Подключение к VK API
    vk_session = vk_api.VkApi(token='')
    vk = vk_session.get_api()

    try:
        members = []
        count = 1000
        offset = 0
        while True:
            response = vk.groups.getMembers(
                group_id=group_id,
                fields="bdate,city,home_town,career,universities",
                offset=offset,
                count=count
            )
            members.extend(response['items'])
            offset += count
            if offset >= response['count']:
                break
    except Exception as e:
        return f"Ошибка при получении подписчиков: {e}"

    today = datetime.today()
    filtered = []

    for user in members:
        user_data = {
            "ID": user['id'],
            "Имя": user.get("first_name", ""),
            "Фамилия": user.get("last_name", "")
        }

                # Обработка даты рождения и возраста
        bdate = user.get("bdate")
        age = None
        if bdate and len(bdate.split('.')) == 3:
            try:
                bdate_obj = datetime.strptime(bdate, "%d.%m.%Y")
                age = today.year - bdate_obj.year - ((today.month, today.day) < (bdate_obj.month, bdate_obj.day))
            except ValueError:
                pass
        user_data["Возраст"] = age if age is not None else ""


        # Фильтрация по возрасту
        if exact_age:
            if not age or age != int(exact_age):
                continue
        elif age_range:
            try:
                a, b = map(int, age_range.split('-'))
                if not age or not (a <= age <= b):
                    continue
            except:
                continue

        # Местоположение
        if include_location:
            user_data["Родной город"] = user.get("home_town", "")
            user_data["Город 'Контакты'"] = user.get("city", {}).get("title", "")
            career_city = user.get("career")
            if career_city and isinstance(career_city, list) and len(career_city) > 0:
                user_data["Город 'Карьера'"] = career_city[0].get("city_name", "")
            else:
                user_data["Город 'Карьера'"] = ""

        # Образование
        if include_education:
            unis = user.get("universities")
            if unis and isinstance(unis, list) and len(unis) > 0:
                uni = unis[0]
                user_data["Вуз"] = uni.get("name", "")
                user_data["Факультет"] = uni.get("faculty_name", "")
                user_data["Год выпуска"] = uni.get("graduation", "")
            else:
                user_data["Вуз"] = ""
                user_data["Факультет"] = ""
                user_data["Год выпуска"] = ""

        # Карьера
        if include_career:
            careers = user.get("career")
            if careers and isinstance(careers, list) and len(careers) > 0:
                job = careers[0]
                user_data["Место работы"] = job.get("company", "")
                user_data["Должность"] = job.get("position", "")
                user_data["Год начала"] = job.get("from", "")
                user_data["Год окончания"] = job.get("until", "")
            else:
                user_data["Место работы"] = ""
                user_data["Должность"] = ""
                user_data["Год начала"] = ""
                user_data["Год окончания"] = ""

        filtered.append(user_data)
    
    # Создание Excel-файла
    wb = Workbook()
    ws = wb.active
    ws.append(list(filtered[0].keys()) if filtered else ["Нет данных"])
    for item in filtered:
        ws.append(list(item.values()))

    file_stream = io.BytesIO()
    wb.save(file_stream)
    file_stream.seek(0)

    return send_file(
        file_stream,
        as_attachment=True,
        download_name='filtered_subscribers.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

@app.route('/classify', methods=['GET', 'POST'])
def classify():
    if request.method == 'POST':
        uploaded_files = []
        labels = []

        subscribers_file = request.files.get('subscribers')
        if not subscribers_file or subscribers_file.filename == "":
            return "Пожалуйста, загрузите файл с подписчиками."

        subscribers_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(subscribers_file.filename))
        subscribers_file.save(subscribers_path)

        for i in range(1, 3):  # можно указать одну или две группы
            file = request.files.get(f'group{i}')
            label = request.form.get(f'label{i}', '').strip()

            if file and file.filename and label:
                path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file.filename))
                file.save(path)
                uploaded_files.append(path)
                labels.append(label)

        result_df = classify_users(subscribers_path, uploaded_files, labels)
        filename = f"result_{datetime.now().strftime('%d-%m')}.xlsx"
        result_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        save_with_summary(result_df, result_path)

        return send_file(result_path, as_attachment=True)

    return render_template('classify.html')

# ========== ОБРАБОТКА ДАТ ==========

def parse_date_safe(value):
    if pd.isna(value):
        return None
    if isinstance(value, datetime):
        return value
    try:
        return pd.to_datetime(str(value), dayfirst=True, errors='coerce')
    except:
        return None

def extract_day_month(date_val):
    dt = parse_date_safe(date_val)
    if pd.notna(dt):
        return dt.strftime('%d.%m')
    return ""

def extract_full_date(date_val):
    dt = parse_date_safe(date_val)
    if pd.notna(dt):
        return dt.strftime('%d.%m.%Y')
    return ""


# ========== ОБРАБОТКА ТЕКСТА ==========

def normalize(text):
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
    norm = normalize(name)
    return name_variations.get(norm, norm)

def load_interest_keywords():
    with open("interests_keywords.json", "r", encoding="utf-8") as f:
        return json.load(f)

def extract_interests_from_text(text, keywords_map):
    text = text.lower()
    result = []
    for category, keywords in keywords_map.items():
        for word in keywords:
            if re.search(r'\b' + re.escape(word) + r'\b', text):
                result.append(category)
    return result

# ========== КЛАССИФИКАЦИЯ ==========

def classify_users(subscribers_path, group_paths, group_labels):
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
            sub_name = name_cache.setdefault(sub["Имя"], normalize_name(sub["Имя"]))
            sub_surname = surname_cache.setdefault(sub["Фамилия"], normalize(sub["Фамилия"]))
            sub_birth_full = extract_full_date(sub.get("Дата рождения", ""))
            sub_birth_dm = extract_day_month(sub.get("Дата рождения", ""))