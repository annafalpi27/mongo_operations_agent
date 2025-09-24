
import json
import os
import re
from typing import TypedDict
from typing_extensions import Annotated
from dotenv import load_dotenv

from langchain.chat_models import init_chat_model

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages

from src.my_mongo_client import MyMongoClient


class State(TypedDict):
    messages: Annotated[list, add_messages]
    mongo_op: str | None


class MongoAgent():

    def __init__(self):
        self.llm = init_chat_model(
            model="openai/gpt-4.1-nano",
            model_provider="openai",
            api_key=os.environ["GITHUB_TOKEN"],
            base_url="https://models.github.ai/inference"
        )
        self.graph_builder = StateGraph(State)
        self.supported_operations = ["find", "insert", "update", "delete"]

    def operation_detection(self, state: State) -> dict:
        # we will call an LLM to determine which operation the user wants
        last_message = state["messages"][-1]
        response = self.llm.invoke([
            {
                "role": "assistant",
                "content": (
                    f"Detect the mongo operation determined by the user: {last_message.content}. "
                    f"Choose between {self.supported_operations}. Respond with the operation name only. "
                    "If no operation detected, respond with None."
                )
            }
        ])

        if response.content.strip() in self.supported_operations:
            return {"mongo_op": response.content.strip().lower()}

        return {"mongo_op": "invalid"}

    def router(self, state: State) -> dict:
        # determine which translator we want to use
        operation = state["mongo_op"]
        match operation:
            # next_node key in state is generated dynamically by the router
            case "insert":
                return {"next_node": "mongo_insert"}
            case "find":
                return {"next_node": "mongo_find"}
            case "update":
                return {"next_node": "mongo_update"}
            case "delete":
                return {"next_node": "mongo_delete"}
            case _:
                return {"next_node": "invalid_operation"}
            
    # we are building multiple functions to enable conditional nodes
    def mongo_update(self, state: State) -> dict:
        last_message = state["messages"][-1]
        update_response = self.llm.invoke([
            {
                "role": "system",
                "content": (
                    "You are a MongoDB update query generator. "
                    f"Using this natural language query: {last_message.content} "
                    "Extract the document ID and new description for updating the document. "
                    "Rules:\n"
                    "1. Only the 'description' field can be updated\n"
                    "2. Both _id and description must be clearly identifiable from the user's request\n"
                    "3. Output format: {'_id': 'topic_name', 'description': 'new_description_text'}\n"
                    "4. If multiple IDs are mentioned, separate them by a | \n"
                    "5. If either ID or description cannot be extracted, respond with {}\n"
                    "6. Give me ONLY the JSON document, no additional text"
                )
            }
        ])
        raw_response = update_response.content
        if len(raw_response.split("|"))>1:  
            print("Multiple documents detected. Please insert one document at a time.")
            return {"messages": ["Multiple documents detected. Please delete one document at a time."]}
        
        parsed_query = self.normalize_llm_json(raw_response.strip())

        if parsed_query and '_id' in parsed_query and 'description' in parsed_query:
            with MyMongoClient() as client:
                db = client["news_hub"]
                collection = db["topics"]
                result = collection.update_one(
                    {"_id": parsed_query['_id']},
                    {"$set": {"description": parsed_query['description']}}
                )
                
                if result.matched_count > 0:
                    print(f"Successfully updated description for document with ID: {parsed_query['_id']}")
                else:
                    print(f"No document found with ID: {parsed_query['_id']}")
        else:
            print("Could not determine both ID and new description.")

    def mongo_delete(self, state: State) -> dict:
        last_message = state["messages"][-1]
        delete_response = self.llm.invoke([
            {
                "role": "system",
                "content": (
                    "You are a MongoDB delete query ID extractor. "
                    f"Using this natural language query: {last_message.content} "
                    "Extract the document ID to delete documents. "
                    "Rules:\n"
                    "1. The ID must be clearly identifiable from the user's request\n"
                    "3. If multiple IDs are mentioned, separate them by a | \n"
                    "4. Output format: {'_id': 'topic_name'}\n"
                    "5. If no valid ID can be extracted, respond with {}\n"
                    "6. Give me ONLY the JSON document, no additional text"
                )
            }
        ])
        raw_response = delete_response.content
        if len(raw_response.split("|"))>1:
            print("Multiple documents detected. Please insert one document at a time.")
            return {"messages": ["Multiple documents detected. Please delete one document at a time."]}
        
        parsed_query = self.normalize_llm_json(raw_response.strip())

        if parsed_query and '_id' in parsed_query:
            try:
                with MyMongoClient() as client:
                    db = client["news_hub"]
                    collection = db["topics"]
                    result = collection.delete_one({"_id": parsed_query['_id']})
                    
                    if result.deleted_count > 0:
                        print(f"Successfully deleted document with ID: {parsed_query['_id']}")
                    else:
                        print(f"No document found with ID: {parsed_query['_id']}")
            except Exception as e:
                print(f"Error deleting document: {e}")
        else:
            print("Could not determine a valid ID to delete.")

    def mongo_insert(self, state: State) -> dict:
        last_message = state["messages"][-1]
        insert_response = self.llm.invoke([
            {
                "role": "system",
                "content": (
                    "You are a MongoDB insert query generator. "
                    f"Using this natural language query {last_message.content} "
                    "Generate insert documents for a 'topics' collection. "
                    "Rules:\n"
                    "1. _id must be a single lowercase word (politics, culture, economics, etc.)\n"
                    "2. Only include 'description' field if explicitly mentioned\n"
                    "3. If multiple IDs are mentioned, separate them by a | \n"
                    "4. Output format: {'_id': 'topic_name', 'description': 'description_text'}\n"
                    "5. If no valid topic can be extracted, respond with {}\n"
                    "6. Give me ONLY the JSON document, no additional text"
                )
         }
        ])
        raw_response = insert_response.content
        raw_response.split("|") 
        if len(raw_response.split("|"))>1:
            print("Multiple documents detected. Please insert one document at a time.")
            return {"messages": ["Multiple documents detected. Please insert one document at a time."]}
        
        parsed_document = self.normalize_llm_json(raw_response.strip())

        if parsed_document and '_id' in parsed_document:
                try:
                    with MyMongoClient() as client:
                        db = client["news_hub"]
                        collection = db["topics"]
                        result = collection.insert_one(parsed_document)
                        print(f"Inserted document with ID: {result.inserted_id}")
                except Exception as e:
                    print(f"Error inserting document: {e}")
        else:
            print("Could not determine a valid ID to insert.")

    def mongo_find(self, state: State) -> dict:
        last_message = state["messages"][-1]
        filter_response = self.llm.invoke([
            {
                "role": "assistant",
                "content": (
                    f"You are a MongoDB query generator. "
                    f"Using this natural language query: '{last_message.content}'\n"
                    "Generate the MongoDB FILTER (and optionally PROJECTION) to retrieve the desired information.\n"
                    "Rules:\n"
                    "1. Provide ONLY the FILTER object, surrounded by {}.\n"
                    "2. If a PROJECTION is required, provide it after the FILTER, separated by '|', also surrounded by {}.\n"
                    "3. Include fields with 1 and exclude fields with 0 in the PROJECTION.\n"
                    "4. Do NOT include any extra words like 'query', 'filter', or explanations.\n"
                    "5. If no filter can be generated, respond with {}.\n"
                    "6. Example output:\n"
                    "   {'field': 'value'} | {'field1': 1, 'field2': 0}\n"
                    "7. Respond with ONLY the JSON objects, no additional text."
                )
            }
        ])

        raw_response = filter_response.content
        mongo_filter, projection = raw_response.split("|") if "|" in raw_response else (raw_response, "{}")
        parsed_mongo_filter = self.normalize_llm_json(mongo_filter.strip())
        projection = self.normalize_llm_json(projection.strip())
        with MyMongoClient() as client:
            db = client["news_hub"]
            collection = db["topics"]
            result  =collection.find_one(
                filter=parsed_mongo_filter,
                projection=projection
            )
        if result:
            print(f"Document retrieved with filter: {mongo_filter}: {result}")
        else: 
            print("No document matched the query.")

    def invalid_operation(self, state: State) -> dict:
        return {"messages": [f"Invalid operation. Supported operations are: {self.supported_operations}"]}
    
    def create_graph(self):
        self.graph_builder.add_node("operation_detection", self.operation_detection)
        self.graph_builder.add_node("router", self.router)
        self.graph_builder.add_node("mongo_insert", self.mongo_insert) 
        self.graph_builder.add_node("mongo_find", self.mongo_find)
        self.graph_builder.add_node("mongo_update", self.mongo_update)
        self.graph_builder.add_node("mongo_delete", self.mongo_delete)
        self.graph_builder.add_node("invalid_operation", self.invalid_operation)

        self.graph_builder.add_edge(START, "operation_detection")
        self.graph_builder.add_edge("operation_detection", "router")
        self.graph_builder.add_conditional_edges(
            "router",
            lambda state: state["next_node"],
            path_map={
                "mongo_insert": "mongo_insert",
                "mongo_find": "mongo_find",
                "mongo_update": "mongo_update",
                "mongo_delete": "mongo_delete",
                "invalid_operation": "invalid_operation"
            }
        )
        self.graph_builder.add_edge("mongo_insert", END)
        self.graph_builder.add_edge("mongo_find", END)
        self.graph_builder.add_edge("mongo_update", END)
        self.graph_builder.add_edge("mongo_delete", END)
        self.graph_builder.add_edge("invalid_operation", END)
        self.graph = self.graph_builder.compile()

    def run(self) -> str:
        state = {"messages": [], "mongo_op": None}
        self.create_graph()
        
        while True:
                
            user_input = input("Input MongoDB operation with Natural Language: ")
            if user_input.lower()=="exit":
                print("Bye!")
                break
            
            state["messages"] = state.get("messages", []) + [{"role": "user", "content": user_input}]
            state = self.graph.invoke(state)

            if state.get("messages") and len(state["messages"]) > 0:
                last_message = state["messages"][-1]

    def normalize_llm_json(self, s: str):
        # Trim whitespace and surrounding quotes
        s = s.strip().strip('"').strip("'")
        
        s = re.sub(r"([{,]\s*)'([^']+)'\s*:", r'\1"\2":', s)
        s = re.sub(r":\s*'([^']+)'(\s*[},])", r': "\1"\2', s)
        s = re.sub(r'"id":', r'"_id":', s)

        return json.loads(s)

if __name__ == "__main__":

    print(
        "MongoDB Agent:\n"
        "Supported operations:\n"
        "- Insert / Update / Delete:\n"
        "    - Modify documents by _id.\n"
        "    - Only one document at a time.\n"
        "    - Only 'description' field can be added or updated.\n"
        "- Find:\n"
        "    - Generate query from natural language.\n"
        "    - Optional fields projection is supported.\n"
    )

    load_dotenv()
    agent = MongoAgent()
    agent.run()