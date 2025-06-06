import psycopg2
import os
import json
import asyncio
import re
from litellm import completion
from agents import Agent

# Database configuration
hostname = 'localhost'
database = 'hoteldb'
username = 'postgres'
pwd = 'Gautham@123'
port_id = 5432
conn = None
cur = None

# File paths
OUTPUT_DIR = "hotel_data"
os.makedirs(OUTPUT_DIR, exist_ok=True)
chat_log_path = os.path.join(OUTPUT_DIR, "chat_logs.txt")
metadata_path = os.path.join(OUTPUT_DIR, "metadata.txt")

# API configuration
os.environ["GROQ_API_KEY"] = "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"

def append_to_chat_log(role, message):
    with open(chat_log_path, "a", encoding="utf-8") as f:
        f.write(f"{role}: {message}\n")

def read_chat_log():
    if os.path.exists(chat_log_path):
        with open(chat_log_path, "r", encoding="utf-8") as f:
            return f.read()
    return ""

def read_metadata():
    if os.path.exists(metadata_path):
        with open(metadata_path, "r", encoding="utf-8") as f:
            return f.read()
    return ""

class MyRunner:
    def run(self, agent, input_text):
        chat_context = read_chat_log()
        metadata = read_metadata()
        
        messages = [
            {
                "role": "system",
                "content": f"{agent.instructions}\nPrevious conversation context:\n{chat_context}"
                           f"\nmetadata:\n{metadata}"
            },
            {"role": "user", "content": input_text}
        ]
        
        print(f"[AgentContextBuilt] {agent.name}: Constructed prompt.")

        response = completion(
            model="groq/llama3-8b-8192",
            messages=messages,
            temperature=0.3,
            max_tokens=400
        )
        print(f"[AgentUpdatedStreamEvent] {agent.name} complete.")
        if agent.name == "Customer response":
            append_to_chat_log("user", input_text)
            append_to_chat_log("hotel", response.choices[0].message.content)
        return response

    def run2(self, agent, input_text: str, data_list: list) -> list:
        print(f"\n[AgentStarted] {agent.name} received input.")
        chat_context = read_chat_log()
        metadata = read_metadata()

        messages = [
            {
                "role": "system",
                "content": f"{agent.instructions}\nPrevious conversation context:\n{chat_context}\nMetadata:\n{metadata}\ndata:\n{data_list}"
            },
            {"role": "user", "content": input_text}
        ]

        print(f"[AgentContextBuilt] {agent.name}: Constructed prompt.")

        response = completion(
            model="groq/meta-llama/llama-4-scout-17b-16e-instruct",
            messages=messages,
            temperature=0.3,
            max_tokens=400
        )

        print(f"[AgentUpdatedStreamEvent] {agent.name} complete.")
        if agent.name == "Customer response":
            append_to_chat_log("user", input_text)
            append_to_chat_log("hotel", response.choices[0].message.content)

        return response
Runner = MyRunner()


try:
    # Database connection
    conn = psycopg2.connect(
        host=hostname,
        dbname=database,
        user=username,
        password=pwd,
        port=port_id
    )
    cur = conn.cursor()

    def execute_sql_from_response(response_content):
    # Extract all code blocks (markdown style, with optional language specifier)
        sql_blocks = re.findall(r"```(?:sql)?(.*?)```", response_content, re.DOTALL)
        
        if not sql_blocks:
            print("No SQL code blocks found!")
            return []

        results_list = []  # List to store results of executed SQL queries
        cur = conn.cursor()

        for block in sql_blocks:
            # Split each block into individual statements (split by semicolon)
            statements = [stmt.strip() for stmt in block.strip().split(';') if stmt.strip()]
            for stmt in statements:
                try:
                    print("Executing:", stmt[:100])  # Print first 100 chars for brevity
                    cur.execute(stmt)
                    
                    if stmt.strip().lower().startswith("select"):
                        # Fetch and convert SELECT results to strings
                        results = cur.fetchall()
                        results_as_strings = [str(row) for row in results]
                        results_list.extend(results_as_strings)  # Add results to the list
                        print(results_list)
                    conn.commit()
                    print(f"Executed SQL: {stmt[:100]}...")

                except Exception as e:
                    conn.rollback()
                    print(f"Failed to execute SQL: {stmt[:100]}...\nError: {str(e)}")
                    return []

        return results_list

except Exception as error:
    print(f"Database error: {error}")


insertion_agent = Agent(
    name="postgresql query agent",
    instructions="""You are a PostgreSQL query agent. read the meta data throughly and  Carefully read the conversation to understand the data to be inserted only if the user commits to his booking. 
    Generate SQL INSERT/Update statements for the existing table.(only if user confirms his booking)
    table use auto-incrementing booking ID; all values must be explicitly provided.
      Once the user confirms the data, output only the SQL code—no explanations or additional text. be strict about the constraints 
      Provide all statements together in one response.(dont give unnecessary inserts if user is asking for update just update if user is asking to do a new booking then only insert)
    if the user states he want to update someting and confirms his update after validating his email then give update sql query for what he requested
    Always return your SQL queries inside markdown code blocks using triple backticks with 'sql' specified, like this:
```sql
SELECT * FROM customers;"""
)

data_retrieval_agent = Agent(
    name="postgresql query agent select",
    instructions="""Your task is to read the meta data and chat throughly and generate SQL SELECT statements  (ONLY SELECT ignore insertion and update)

- wait till the user provides the selector for booking his room like "small or large or medium" retrieve only using this selector dont use any other selector (dont use date as selector)
- If the user does **not** mention these, do **not** generate any SQL. 
- and reply with "i am the data retrieval agent"
- Do **not** retrieve all data; only select data relevant to the user's interest.
- , include WHERE room_type clauses based on the user's input. (dont use any other selector always only use room type)-without giving any other additional message strictly follow these conditions only
    Always return your SQL queries inside markdown code blocks using triple backticks with 'sql' specified, like this:

```sql
SELECT * FROM customers; 
   """
)

response_agent = Agent(
    name="Customer response",
    instructions="""You are the receptionist at a hotel. Do not mention the hotel name or greet the user.

Your task is to guide the user through a booking or inquiry process by asking only relevant, progressive questions.

1. Begin by asking what the user is looking for
2. Once they indicate their interest, begin collecting complete customer details.
3. Then, ask for specific booking preferences such as room type, date, time, or any other relevant requirement.
4. Use the data to check availability based on the user's request.(mainly check the dates)- a room can never be shared between two customers
5. If the room is already booked for the requested time, inform the user of the next available time and ask if they would like to choose a different room type.
the the start time and end time of any booking should not co incide with other booking of the same room
6. If available, provide the room type, availability window, and price.
7. Once all information is gathered, ask the user for confirmation to proceed with the booking. 
8. if the user is inquiring about the data, just know the data is consistent to what the user is requestion [for example if the user is looking for those who have booked medium rooms the names of those who booked medium room willbe in the data], the data doesnt need to have complete datails, just answer with what is available precise to the user request
9. Always use simple, clear English. (you are not a sql query agent just get data from data if available),(if the user is trying to change data just ask for the email of the row the data needs to be changed then ask for a confirm message)
"""
)


def get_data(user_input: str) -> str:
    return  Runner.run(data_retrieval_agent, user_input)

def get_response(user_input: str, data_list: list) -> str:
    return  Runner.run2(response_agent, user_input, data_list)

def insert_data(user_input: str) -> str:
    return  Runner.run(insertion_agent, user_input)


def main():
    print("Hotel Chatbot: Hello! Athens Hotel How can I assist you today?")
    data_list=[]
    while True:
        try:
            user_input = input("\nYou: ")
            if user_input.lower() in ["exit", "quit", "bye","confirm"]:
                print("Hotel Chatbot: Goodbye! Have a great day!")
                break
            
            data =  get_data(f"(user input:{user_input})the user wont continually give valid input read the chat history and understand what you should look for, and write appropriate sql query")
            llm_response1 = data.choices[0].message.content
            print(f"\nHotel Chatbot(select): {llm_response1}")
            data_list=execute_sql_from_response(f"{llm_response1}")

            response =  get_response(user_input ,data_list)
            print(f"\nHotel Chatbot: {response.choices[0].message.content}")

        except KeyboardInterrupt:
            print("\nSession ended.")
            break

    response2 =insert_data("generate insertion/update queries only")
    llm_response2=response2.choices[0].message.content
    print(f"\nHotel Chatbot(insert/update): {llm_response2}")
    x=execute_sql_from_response(f"{llm_response2}")
if __name__ == "__main__":
    try:
        main()
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
