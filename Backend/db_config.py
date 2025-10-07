import psycopg2

def get_db_connection():
    return psycopg2.connect(
        host="ep-icy-glitter-adlj103n-pooler.c-2.us-east-1.aws.neon.tech",  # only hostname
        dbname="event_system",                                              # database name
        user="neondb_owner",                                                # Neon username
        password="npg_IFCGW9v4OPXm",                                        # Neon password
        sslmode="require"
    )
