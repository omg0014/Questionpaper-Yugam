import os
import psycopg2

def get_db_connection():
    database_url = os.getenv("postgresql://abhi:NnAwz8YBkIOoybehPpMMvL0fSwM6pNeo@dpg-d5r7mvhr0fns73e0ff8g-a/question_paper_db_baav")
    return psycopg2.connect(database_url, sslmode="require")
