-- Run this file while connected to the default `postgres` database.
-- CREATE DATABASE cannot run inside a transaction block.
-- If the nerva database already exists, do not run this statement again.

CREATE DATABASE nerva
    WITH
    OWNER = postgres
    ENCODING = 'UTF8'
    CONNECTION LIMIT = -1;

