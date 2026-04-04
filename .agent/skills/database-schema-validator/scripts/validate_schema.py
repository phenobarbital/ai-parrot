import sys
import re

def validate_schema(filename):
    """
    Validates a SQL schema file against internal policy:
    1. Table names must be snake_case.
    2. Every table must have a primary key named 'id'.
    3. No 'DROP TABLE' statements allowed (safety).
    """
    try:
        with open(filename, 'r') as f:
            content = f.read()
            
        lines = content.split('\n')
        errors = []
        
        # Check 1: No DROP TABLE
        if re.search(r'DROP TABLE', content, re.IGNORECASE):
            errors.append("ERROR: 'DROP TABLE' statements are forbidden.")
            
        # Check 2 & 3: CREATE TABLE checks
        table_defs = re.finditer(r'CREATE TABLE\s+(?P<name>\w+)\s*\((?P<body>.*?)\);', content, re.DOTALL | re.IGNORECASE)
        
        for match in table_defs:
            table_name = match.group('name')
            body = match.group('body')
            
            # Snake case check
            if not re.match(r'^[a-z][a-z0-9_]*$', table_name):
                errors.append(f"ERROR: Table '{table_name}' must be snake_case.")
                
            # Primary key check
            if not re.search(r'\bid\b.*PRIMARY KEY', body, re.IGNORECASE):
                errors.append(f"ERROR: Table '{table_name}' is missing a primary key named 'id'.")

        if errors:
            for err in errors:
                print(err)
            sys.exit(1)
        else:
            print("Schema validation passed.")
            sys.exit(0)
            
    except FileNotFoundError:
        print(f"Error: File '{filename}' not found.")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python validate_schema.py <schema_file>")
        sys.exit(1)
        
    validate_schema(sys.argv[1])
