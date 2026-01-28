-- Supabase 테이블 스키마
-- 점심이야기 식당 정보 및 네이버 발행 큐 테이블

-- 0. likes 테이블 생성 (좋아요 기능)
CREATE TABLE IF NOT EXISTS likes (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    post_id TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 인덱스 추가
CREATE INDEX IF NOT EXISTS idx_likes_post_id ON likes(post_id);
CREATE INDEX IF NOT EXISTS idx_likes_created_at ON likes(created_at DESC);

-- 0-1. views 테이블 생성 (조회수 기능)
CREATE TABLE IF NOT EXISTS views (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    post_id TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 인덱스 추가
CREATE INDEX IF NOT EXISTS idx_views_post_id ON views(post_id);
CREATE INDEX IF NOT EXISTS idx_views_created_at ON views(created_at DESC);

-- 0-2. guestbook 테이블 생성 (방명록 기능)
CREATE TABLE IF NOT EXISTS guestbook (
    id SERIAL PRIMARY KEY,
    nickname TEXT NOT NULL,
    message TEXT NOT NULL,
    reply TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 인덱스 추가
CREATE INDEX IF NOT EXISTS idx_guestbook_created_at ON guestbook(created_at DESC);

-- 1. restaurants 테이블 생성
CREATE TABLE IF NOT EXISTS restaurants (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    name TEXT NOT NULL,
    address TEXT,
    naver_place_id TEXT UNIQUE NOT NULL,
    visit_count INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 인덱스 추가
CREATE INDEX IF NOT EXISTS idx_restaurants_naver_place_id ON restaurants(naver_place_id);

-- 2. naver_publish_queue 테이블에 컬럼 추가
-- 기존 테이블이 있다면 컬럼만 추가
ALTER TABLE naver_publish_queue
ADD COLUMN IF NOT EXISTS restaurant_name TEXT,
ADD COLUMN IF NOT EXISTS restaurant_address TEXT,
ADD COLUMN IF NOT EXISTS naver_place_id TEXT,
ADD COLUMN IF NOT EXISTS visit_count INTEGER DEFAULT 1,
ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS max_retries INTEGER DEFAULT 3,
ADD COLUMN IF NOT EXISTS worker_key TEXT,
ADD COLUMN IF NOT EXISTS published_at TIMESTAMP WITH TIME ZONE;

-- 만약 naver_publish_queue 테이블이 없다면 생성
CREATE TABLE IF NOT EXISTS naver_publish_queue (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    post_id TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    tags JSONB DEFAULT '[]',
    image_url TEXT,
    images JSONB DEFAULT '[]',
    category TEXT DEFAULT '그림일기',
    restaurant_name TEXT,
    restaurant_address TEXT,
    naver_place_id TEXT,
    visit_count INTEGER DEFAULT 1,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    worker_key TEXT,
    status TEXT DEFAULT 'pending', -- pending, processing, published, failed
    naver_url TEXT,
    error_message TEXT,
    published_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 인덱스 추가
CREATE INDEX IF NOT EXISTS idx_naver_queue_post_id ON naver_publish_queue(post_id);
CREATE INDEX IF NOT EXISTS idx_naver_queue_status ON naver_publish_queue(status);
CREATE INDEX IF NOT EXISTS idx_naver_queue_created_at ON naver_publish_queue(created_at DESC);

-- 3. updated_at 자동 업데이트 트리거 함수
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- restaurants 테이블에 트리거 추가
DROP TRIGGER IF EXISTS update_restaurants_updated_at ON restaurants;
CREATE TRIGGER update_restaurants_updated_at
    BEFORE UPDATE ON restaurants
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- naver_publish_queue 테이블에 트리거 추가
DROP TRIGGER IF EXISTS update_naver_queue_updated_at ON naver_publish_queue;
CREATE TRIGGER update_naver_queue_updated_at
    BEFORE UPDATE ON naver_publish_queue
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- 4. Row Level Security (RLS) 설정 (선택사항)
-- 만약 RLS를 사용한다면:
-- ALTER TABLE restaurants ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE naver_publish_queue ENABLE ROW LEVEL SECURITY;

-- 모든 작업 허용하는 정책 (개발/테스트용)
-- CREATE POLICY "Enable all operations" ON restaurants FOR ALL USING (true);
-- CREATE POLICY "Enable all operations" ON naver_publish_queue FOR ALL USING (true);
