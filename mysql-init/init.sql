CREATE DATABASE IF NOT EXISTS raw;
CREATE DATABASE IF NOT EXISTS curated;

CREATE TABLE IF NOT EXISTS raw.raw_penguins (
            id INT,
            species INT,
            island INT,
            bill_length_mm FLOAT,
            bill_depth_mm FLOAT,
            flipper_length_mm INT,
            body_mass_g INT,
            sex INT,
            year INT);

GRANT ALL PRIVILEGES ON raw.* TO 'user'@'%';
GRANT ALL PRIVILEGES ON curated.* TO 'user'@'%';
FLUSH PRIVILEGES;