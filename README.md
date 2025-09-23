# Mongo Operations Agent

This project provides an agent for interacting with a MongoDB  collection using natural language commands. It supports inserting, updating, deleting, and querying documents, including optional field projections.

## Setup

1. **Create and synchronize virtual environment**

```bash
uv sync
```

2. **Set credentials**

   Add your MongoDB credentials and GitHub model credentials in a .env file at the root of the project. Visit [https://github.com/marketplace?type=models]() to create a Github models credentials

## Running the Agent

Run the agent script:

```
python mongo_operations_agent.py
```
