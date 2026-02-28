-- Instagram 발행 큐 테이블

CREATE TABLE IF NOT EXISTS instagram_publish_queue (
    id SERIAL PRIMARY KEY,
    post_id TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    tags JSONB DEFAULT '[]',
    image_url TEXT,
    images JSONB DEFAULT '[]',
    category TEXT DEFAULT 'diary',
    restaurant_name TEXT,
    restaurant_address TEXT,
    naver_place_id TEXT,
    visit_count INTEGER DEFAULT 1,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    worker_key TEXT,
    status TEXT DEFAULT 'pending',  -- pending, processing, published, failed
    instagram_url TEXT,
    instagram_media_id TEXT,
    error_message TEXT,
    published_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_ig_queue_post_id ON instagram_publish_queue(post_id);
CREATE INDEX IF NOT EXISTS idx_ig_queue_status ON instagram_publish_queue(status);
CREATE INDEX IF NOT EXISTS idx_ig_queue_created_at ON instagram_publish_queue(created_at DESC);

-- updated_at 자동 업데이트 트리거
DROP TRIGGER IF EXISTS update_ig_queue_updated_at ON instagram_publish_queue;
CREATE TRIGGER update_ig_queue_updated_at
    BEFORE UPDATE ON instagram_publish_queue
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
