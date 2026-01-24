-- SQL script to create the visitors table for cookie-based visitor sessions
-- This table should be created in your existing database

CREATE TABLE `visitors` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `visitor_id` VARCHAR(50) NOT NULL,
  `first_visit` DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
  `last_visit` DATETIME NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `visit_count` INT NULL DEFAULT 1,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `visitor_id_UNIQUE` (`visitor_id` ASC) VISIBLE
);

-- Add visitor_id column to papers table if it doesn't exist
ALTER TABLE `papers` 
ADD COLUMN IF NOT EXISTS `visitor_id` VARCHAR(50) NULL AFTER `answer_key_path`;

-- Add foreign key constraint to link papers to visitors
ALTER TABLE `papers` 
ADD CONSTRAINT `fk_papers_visitor`
  FOREIGN KEY (`visitor_id`)
  REFERENCES `visitors` (`visitor_id`)
  ON DELETE SET NULL
  ON UPDATE NO ACTION;