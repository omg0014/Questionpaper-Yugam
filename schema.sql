-- =========================================================================
-- Intelligent Paper Generator — Database Schema
-- Target: MySQL 8.0+ (utf8mb4 for full Devanagari support)
--
-- Tables: boards -> classes -> subjects -> chapters -> questions
--         visitors -> papers -> paper_questions
--
-- To import in MySQL Workbench:
--   1. Open Workbench, connect to your MySQL server.
--   2. File -> Open SQL Script -> select this file (schema.sql).
--   3. Click the lightning-bolt icon (Execute) or Ctrl+Shift+Enter.
--   4. Refresh the Navigator (Schemas tab) to see question_paper_db.
-- Or via CLI:
--   mysql -u root -p < schema.sql
-- =========================================================================

CREATE DATABASE IF NOT EXISTS `question_paper_db`
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
USE `question_paper_db`;

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- -------------------------------------------------------------------------
-- 1) boards: top-level curriculum boards (CBSE, ICSE, State Board, ...)
-- -------------------------------------------------------------------------
DROP TABLE IF EXISTS `boards`;
CREATE TABLE `boards` (
  `board_id` INT NOT NULL AUTO_INCREMENT,
  `name`     VARCHAR(50) NOT NULL,
  PRIMARY KEY (`board_id`),
  UNIQUE KEY `uq_boards_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -------------------------------------------------------------------------
-- 2) classes: e.g. Class 1..12 under each board
-- -------------------------------------------------------------------------
DROP TABLE IF EXISTS `classes`;
CREATE TABLE `classes` (
  `class_id`     INT NOT NULL AUTO_INCREMENT,
  `board_id`     INT NOT NULL,
  `class_number` INT NOT NULL,
  PRIMARY KEY (`class_id`),
  KEY `idx_classes_board` (`board_id`),
  CONSTRAINT `fk_classes_board`
    FOREIGN KEY (`board_id`) REFERENCES `boards`(`board_id`)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -------------------------------------------------------------------------
-- 3) subjects: Math, Science, Social Studies, ... (bilingual labels)
-- -------------------------------------------------------------------------
DROP TABLE IF EXISTS `subjects`;
CREATE TABLE `subjects` (
  `subject_id` INT NOT NULL AUTO_INCREMENT,
  `class_id`   INT NOT NULL,
  `name_en`    VARCHAR(100) NOT NULL,
  `name_hi`    VARCHAR(100) NOT NULL,
  PRIMARY KEY (`subject_id`),
  KEY `idx_subjects_class` (`class_id`),
  CONSTRAINT `fk_subjects_class`
    FOREIGN KEY (`class_id`) REFERENCES `classes`(`class_id`)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -------------------------------------------------------------------------
-- 4) chapters: per-subject chapter list (bilingual)
-- -------------------------------------------------------------------------
DROP TABLE IF EXISTS `chapters`;
CREATE TABLE `chapters` (
  `chapter_id`     INT NOT NULL AUTO_INCREMENT,
  `subject_id`     INT NOT NULL,
  `chapter_number` INT NULL,
  `title_en`       VARCHAR(255) NOT NULL,
  `title_hi`       VARCHAR(255) NOT NULL,
  PRIMARY KEY (`chapter_id`),
  KEY `idx_chapters_subject` (`subject_id`),
  CONSTRAINT `fk_chapters_subject`
    FOREIGN KEY (`subject_id`) REFERENCES `subjects`(`subject_id`)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -------------------------------------------------------------------------
-- 5) questions: the question bank (linked to a chapter; bilingual content)
-- -------------------------------------------------------------------------
DROP TABLE IF EXISTS `questions`;
CREATE TABLE `questions` (
  `id`            INT NOT NULL AUTO_INCREMENT,
  `chapter_id`    INT NOT NULL,
  `question_type` VARCHAR(50) NULL,
  `difficulty`    VARCHAR(20) NULL,
  `marks`         INT NULL,
  `question_text` TEXT NULL,
  `options`       JSON NULL,
  `answer`        TEXT NULL,
  `source`        VARCHAR(50) NULL,
  `explanation`   TEXT NULL,
  `language`      VARCHAR(20) NOT NULL DEFAULT 'english',
  PRIMARY KEY (`id`),
  KEY `idx_questions_chapter`   (`chapter_id`),
  KEY `idx_questions_type`      (`question_type`),
  KEY `idx_questions_marks`     (`marks`),
  KEY `idx_questions_language`  (`language`),
  CONSTRAINT `fk_questions_chapter`
    FOREIGN KEY (`chapter_id`) REFERENCES `chapters`(`chapter_id`)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -------------------------------------------------------------------------
-- 6) visitors: anonymous cookie-based session tracking
-- -------------------------------------------------------------------------
DROP TABLE IF EXISTS `visitors`;
CREATE TABLE `visitors` (
  `id`          INT NOT NULL AUTO_INCREMENT,
  `visitor_id`  VARCHAR(50) NOT NULL,
  `first_visit` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `last_visit`  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                                ON UPDATE CURRENT_TIMESTAMP,
  `visit_count` INT NULL DEFAULT 1,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_visitors_visitor_id` (`visitor_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -------------------------------------------------------------------------
-- 7) papers: generated paper metadata + file paths
-- -------------------------------------------------------------------------
DROP TABLE IF EXISTS `papers`;
CREATE TABLE `papers` (
  `id`               INT NOT NULL AUTO_INCREMENT,
  `paper_id`         VARCHAR(50) NULL,
  `exam_name`        VARCHAR(100) NULL,
  `school_name`      VARCHAR(100) NULL,
  `board`            VARCHAR(50) NULL,
  `class_`           VARCHAR(10) NULL,
  `subject`          VARCHAR(100) NULL,
  `created_at`       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `total_questions`  INT NULL,
  `total_marks`      INT NULL,
  `pdf_path`         VARCHAR(255) NULL,
  `word_path`        VARCHAR(255) NULL,
  `answer_key_path`  VARCHAR(255) NULL,
  `visitor_id`       VARCHAR(50) NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_papers_paper_id` (`paper_id`),
  KEY `idx_papers_visitor`         (`visitor_id`),
  KEY `idx_papers_created_at`      (`created_at`),
  CONSTRAINT `fk_papers_visitor`
    FOREIGN KEY (`visitor_id`) REFERENCES `visitors`(`visitor_id`)
    ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -------------------------------------------------------------------------
-- 8) paper_questions: join table linking generated papers to their questions
-- -------------------------------------------------------------------------
DROP TABLE IF EXISTS `paper_questions`;
CREATE TABLE `paper_questions` (
  `id`            INT NOT NULL AUTO_INCREMENT,
  `paper_id`      VARCHAR(50) NULL,
  `question_id`   INT NULL,
  `question_text` TEXT NULL,
  `type`          VARCHAR(50) NULL,
  `difficulty`    VARCHAR(20) NULL,
  `marks`         INT NULL,
  `options`       JSON NULL,
  `answer`        TEXT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_pq_paper`    (`paper_id`),
  KEY `idx_pq_question` (`question_id`),
  CONSTRAINT `fk_pq_paper`
    FOREIGN KEY (`paper_id`) REFERENCES `papers`(`paper_id`)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

SET FOREIGN_KEY_CHECKS = 1;

-- =========================================================================
-- Optional seed data (minimal). Comment-out if you'll load from dump.sql.
-- =========================================================================

INSERT INTO `boards` (`name`) VALUES
  ('CBSE'), ('ICSE'), ('State Board')
ON DUPLICATE KEY UPDATE `name` = VALUES(`name`);

-- Seed classes 1..12 for each board
INSERT INTO `classes` (`board_id`, `class_number`)
SELECT b.board_id, n.class_number
FROM `boards` b
CROSS JOIN (
  SELECT 1 AS class_number UNION SELECT 2  UNION SELECT 3  UNION SELECT 4
  UNION SELECT 5  UNION SELECT 6  UNION SELECT 7  UNION SELECT 8
  UNION SELECT 9  UNION SELECT 10 UNION SELECT 11 UNION SELECT 12
) n
WHERE NOT EXISTS (
  SELECT 1 FROM `classes` c
  WHERE c.board_id = b.board_id AND c.class_number = n.class_number
);

-- =========================================================================
-- Done. Verify with: SHOW TABLES; SELECT COUNT(*) FROM boards;
-- =========================================================================
