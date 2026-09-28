-- Grain: one row per category. A governed, hand-maintained mapping from
-- products.category (which a rename can silently change -- see P2) to a stable
-- family that survives the rename. Every category theLook currently has is listed
-- here explicitly; a new category introduced later needs a new row added by hand,
-- which is the point -- this table is a piece of governance, not a formula.
--
-- The renamed pair ({{p2_old_category}} / {{p2_new_category}}) is the only case
-- where two category names share one family; family names below match their
-- category name lowercased and underscored.
CREATE OR REPLACE TABLE `{{project}}.{{dataset_star}}.map_category_family` AS
SELECT * FROM UNNEST([
  STRUCT('Accessories' AS category, 'accessories' AS category_family),
  ('Active', 'active'),
  ('Blazers & Jackets', 'blazers_jackets'),
  ('Clothing Sets', 'clothing_sets'),
  ('Dresses', 'dresses'),
  ('Fashion Hoodies & Sweatshirts', 'fashion_hoodies_sweatshirts'),
  ('Intimates', 'intimates'),
  ('Jeans', 'jeans'),
  ('Jumpsuits & Rompers', 'jumpsuits_rompers'),
  ('Leggings', 'leggings'),
  ('Maternity', 'maternity'),
  ('Outerwear & Coats', 'outerwear_coats'),
  ('Pants', 'pants'),
  ('Pants & Capris', 'pants_capris'),
  ('Plus', 'plus'),
  ('Shorts', 'shorts'),
  ('Skirts', 'skirts'),
  ('Sleep & Lounge', 'sleep_lounge'),
  ('Socks', 'socks'),
  ('Socks & Hosiery', 'socks_hosiery'),
  ('Suits', 'suits'),
  ('Suits & Sport Coats', 'suits_sport_coats'),
  ('Swim', 'swim'),
  ('Tops & Tees', 'tops_tees'),
  ('Underwear', 'underwear'),
  ('{{p2_old_category}}', '{{p2_family}}'),
  ('{{p2_new_category}}', '{{p2_family}}')
]);
