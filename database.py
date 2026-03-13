"""
数据库模块
SQLAlchemy 模型定义和数据库连接
"""

import os
import uuid
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, JSON, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/deepagents.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    """用户表"""
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    invite_code = Column(String(50), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)


class InviteCode(Base):
    """邀请码表"""
    __tablename__ = "invite_codes"
    code = Column(String(50), primary_key=True)
    is_used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Resume(Base):
    """简历数据表"""
    __tablename__ = "resumes"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    name = Column(String(100), default="默认简历")
    resume_data = Column(JSON, default=dict)
    photo = Column(Text, default="")
    parsing_status = Column(String(20), default="none")  # none, parsing, completed, failed
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class JobDescription(Base):
    """JD数据表"""
    __tablename__ = "job_descriptions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    company = Column(String(100), default="")
    position = Column(String(100), default="")
    jd_data = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Conversation(Base):
    """对话历史表"""
    __tablename__ = "conversations"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    session_id = Column(String(36), nullable=False)
    title = Column(String(50), nullable=False, default="新会话")
    messages = Column(JSON, default=list)  # 完整的聊天历史
    compressed_context = Column(JSON, default=list)  # 压缩后的上下文（用于性能）
    pending_confirmation = Column(JSON, default=None)  # 待确认状态
    # 双语简历支持（session级别）
    zh_resume = Column(JSON, default=dict)  # 中文简历
    en_resume = Column(JSON, default=dict)  # 英文简历
    jd_data = Column(JSON, default=dict)    # JD数据（从原Resume表迁移）
    photo = Column(Text, default="")  # 证件照（两个语言共用）
    migrated_from_old = Column(Boolean, default=False)  # 是否已从旧表迁移
    last_accessed = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


def get_db():
    """数据库依赖"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """初始化数据库（创建所有表）"""
    Base.metadata.create_all(bind=engine)


# =============================================================================
# 数据访问函数
# =============================================================================

def get_user_by_email(db, email: str):
    """根据邮箱获取用户"""
    return db.query(User).filter(User.email == email).first()


def get_user_by_id(db, user_id: int):
    """根据ID获取用户"""
    return db.query(User).filter(User.id == user_id).first()


def create_user(db, email: str, hashed_password: str, invite_code: str):
    """创建用户"""
    user = User(email=email, hashed_password=hashed_password, invite_code=invite_code)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user_resume(db, user_id: int) -> dict:
    """获取用户简历"""
    resume = db.query(Resume).filter(Resume.user_id == user_id).first()
    return resume.resume_data if resume else {}


def get_parsing_status(db, user_id: int) -> str:
    """获取简历解析状态"""
    try:
        resume = db.query(Resume).filter(Resume.user_id == user_id).first()
        return resume.parsing_status if resume else "none"
    except Exception:
        # 如果表结构有问题，返回默认值
        return "none"


def set_parsing_status(db, user_id: int, status: str):
    """设置简历解析状态"""
    resume = db.query(Resume).filter(Resume.user_id == user_id).first()
    if resume:
        resume.parsing_status = status
    else:
        # 如果简历不存在，先创建
        resume = Resume(user_id=user_id, parsing_status=status)
        db.add(resume)
    db.commit()


def save_user_resume(db, user_id: int, data: dict, name: str = "默认简历", photo: str = None):
    """保存用户简历
    
    Args:
        db: 数据库会话
        user_id: 用户ID
        data: 简历数据JSON
        name: 简历名称
        photo: 证件照base64编码（可选，如果为None则从data中提取）
    """
    print(f"[save_user_resume] 开始保存，用户ID={user_id}")
    print(f"[save_user_resume] 传入 data keys: {list(data.keys()) if isinstance(data, dict) else 'not a dict'}")
    
    # 先获取现有数据（用于保留原有证件照）
    existing_resume = db.query(Resume).filter(Resume.user_id == user_id).first()
    existing_photo = existing_resume.photo if existing_resume and existing_resume.photo else ""
    
    # 提取并分离证件照
    if photo is None:
        photo = data.get('basics', {}).get('photo', '')
    
    # 如果新数据没有 photo但数据库已有 photo，保留原有证件照
    if not photo and existing_photo:
        photo = existing_photo
    
    # 从 data 中移除 photo 字段
    if data and 'basics' in data:
        data = {**data, 'basics': {**data.get('basics', {})}}
        data['basics'].pop('photo', None)
    
    if existing_resume:
        print(f"[save_user_resume] 现有数据存在，basics.name: {existing_resume.resume_data.get('basics', {}).get('name', 'N/A')}")
        print(f"[save_user_resume] 新数据 basics.name: {data.get('basics', {}).get('name', 'N/A')}")
        existing_resume.resume_data = data
        existing_resume.name = name
        existing_resume.photo = photo
    else:
        print(f"[save_user_resume] 创建新简历")
        resume = Resume(user_id=user_id, resume_data=data, name=name, photo=photo)
        db.add(resume)
    db.commit()
    print(f"[save_user_resume] 保存完成")
    return existing_resume if existing_resume else resume


def get_user_jd(db, user_id: int) -> dict:
    """获取用户JD"""
    jd = db.query(JobDescription).filter(JobDescription.user_id == user_id).first()
    return jd.jd_data if jd else {}


def save_user_jd(db, user_id: int, data: dict, company: str = "", position: str = ""):
    """保存用户JD"""
    jd = db.query(JobDescription).filter(JobDescription.user_id == user_id).first()
    if jd:
        jd.jd_data = data
        jd.company = company
        jd.position = position
    else:
        jd = JobDescription(user_id=user_id, jd_data=data, company=company, position=position)
        db.add(jd)
    db.commit()
    return jd


def save_conversation(db, user_id: int, session_id: str, messages: list):
    """保存对话历史"""
    conv = db.query(Conversation).filter(
        Conversation.user_id == user_id,
        Conversation.session_id == session_id
    ).first()
    if conv:
        conv.messages = messages
    else:
        conv = Conversation(user_id=user_id, session_id=session_id, title="新会话", messages=messages)
        db.add(conv)
    db.commit()
    return conv


def get_conversation(db, user_id: int, session_id: str) -> list:
    """获取对话历史"""
    conv = db.query(Conversation).filter(
        Conversation.user_id == user_id,
        Conversation.session_id == session_id
    ).first()
    if conv:
        # 更新最后访问时间
        conv.last_accessed = datetime.utcnow()
        db.commit()
    return conv.messages if conv else []


def check_invite_code(db, code: str) -> bool:
    """检查邀请码是否有效"""
    invite = db.query(InviteCode).filter(InviteCode.code == code).first()
    return invite and not invite.is_used


def use_invite_code(db, code: str):
    """使用邀请码"""
    invite = db.query(InviteCode).filter(InviteCode.code == code).first()
    if invite:
        invite.is_used = True
        db.commit()


def create_invite_code(db, code: str):
    """创建邀请码"""
    invite = InviteCode(code=code)
    db.add(invite)
    db.commit()
    return invite


def save_conversation_context(db, user_id: int, session_id: str, compressed_context: list, pending_confirmation: dict = None):
    """保存压缩后的上下文到数据库"""
    conv = db.query(Conversation).filter(
        Conversation.user_id == user_id,
        Conversation.session_id == session_id
    ).first()
    if conv:
        conv.compressed_context = compressed_context
        if pending_confirmation is not None:
            conv.pending_confirmation = pending_confirmation
        conv.last_accessed = datetime.utcnow()
    else:
        conv = Conversation(
            user_id=user_id,
            session_id=session_id,
            title="新会话",
            compressed_context=compressed_context,
            pending_confirmation=pending_confirmation,
            messages=[]  # 初始化为空，由前端通过 /save_conversation 保存
        )
        db.add(conv)
    db.commit()
    return conv


def get_pending_confirmation(db, user_id: int, session_id: str) -> dict:
    """获取待确认状态"""
    conv = db.query(Conversation).filter(
        Conversation.user_id == user_id,
        Conversation.session_id == session_id
    ).first()
    return conv.pending_confirmation if conv else None


def clear_pending_confirmation(db, user_id: int, session_id: str):
    """清除待确认状态"""
    conv = db.query(Conversation).filter(
        Conversation.user_id == user_id,
        Conversation.session_id == session_id
    ).first()
    if conv:
        conv.pending_confirmation = None
        db.commit()


def get_conversation_context(db, user_id: int, session_id: str) -> list:
    """获取压缩后的上下文（用于性能优化）"""
    conv = db.query(Conversation).filter(
        Conversation.user_id == user_id,
        Conversation.session_id == session_id
    ).first()
    if conv:
        # 更新最后访问时间
        conv.last_accessed = datetime.utcnow()
        db.commit()
        return conv.compressed_context if conv.compressed_context else []
    return []


def cleanup_old_contexts(db, days: int = 7):
    """清理过期上下文（默认7天未访问的）"""
    cutoff = datetime.utcnow() - timedelta(days=days)
    db.query(Conversation).filter(
        Conversation.last_accessed < cutoff
    ).update({"compressed_context": []})
    db.commit()


def delete_conversation_context(db, user_id: int, session_id: str):
    """删除指定会话的上下文"""
    db.query(Conversation).filter(
        Conversation.user_id == user_id,
        Conversation.session_id == session_id
    ).update({"compressed_context": []})
    db.commit()


# =============================================================================
# Session级别的简历访问函数（双语支持）
# =============================================================================

def get_session_resume(db, user_id: int, session_id: str, lang: str = 'zh') -> dict:
    """获取指定session的简历

    Args:
        db: 数据库会话
        user_id: 用户ID
        session_id: 会话ID
        lang: 语言，'zh' 或 'en'

    Returns:
        简历数据字典
    """
    print(f"[DEBUG get_session_resume] user_id={user_id}, session_id={session_id}, lang={lang}")
    conv = db.query(Conversation).filter(
        Conversation.user_id == user_id,
        Conversation.session_id == session_id
    ).first()
    if not conv:
        print(f"[DEBUG get_session_resume] 会话不存在")
        return {}
    
    print(f"[DEBUG get_session_resume] conv.migrated_from_old={conv.migrated_from_old}")
    print(f"[DEBUG get_session_resume] zh_resume keys={list(conv.zh_resume.keys()) if conv.zh_resume else 'None'}")
    print(f"[DEBUG get_session_resume] en_resume keys={list(conv.en_resume.keys()) if conv.en_resume else 'None'}")
    
    # 只有在没有中文简历数据且未迁移过的情况下，才迁移旧数据
    if not conv.migrated_from_old and (not conv.zh_resume or not conv.zh_resume.get('basics')):
        old_resume = get_user_resume(db, user_id)
        if old_resume and isinstance(old_resume, dict) and old_resume.get('basics'):
            # 旧简历默认迁移到中文字段（旧系统没有语言区分）
            conv.zh_resume = old_resume
            conv.migrated_from_old = True
            db.commit()
            print(f"[DEBUG get_session_resume] 已迁移旧简历到 zh_resume")
            # 根据请求的语言返回对应字段
            return conv.zh_resume if lang == 'zh' else conv.en_resume
        else:
            print(f"[DEBUG get_session_resume] 旧简历不存在或无效，跳过迁移")
    elif conv.zh_resume and conv.zh_resume.get('basics'):
        print(f"[DEBUG get_session_resume] zh_resume 已有数据，跳过迁移")
    elif conv.migrated_from_old:
        print(f"[DEBUG get_session_resume] 已标记迁移过，跳过迁移")
    
    resume_field = conv.zh_resume if lang == 'zh' else conv.en_resume
    print(f"[DEBUG get_session_resume] 返回 {lang} 简历, has_data={bool(resume_field)}")
    if resume_field:
        basics = resume_field.get('basics', {})
        print(f"[DEBUG get_session_resume] 返回简历 name={basics.get('name')}, target={basics.get('target_position')}")
        return resume_field
    
    print(f"[DEBUG get_session_resume] 返回空简历")
    return {}


def save_session_resume(db, user_id: int, session_id: str, resume_data: dict, lang: str = 'zh'):
    """保存指定session的简历

    Args:
        db: 数据库会话
        user_id: 用户ID
        session_id: 会话ID
        resume_data: 简历数据
        lang: 语言，'zh' 或 'en'
    """
    print(f"[DEBUG save_session_resume] user_id={user_id}, session_id={session_id}, lang={lang}")
    basics = resume_data.get('basics', {}) if resume_data else {}
    print(f"[DEBUG save_session_resume] 保存简历 name={basics.get('name')}, target={basics.get('target_position')}")
    
    conv = db.query(Conversation).filter(
        Conversation.user_id == user_id,
        Conversation.session_id == session_id
    ).first()
    if not conv:
        # 如果会话不存在，先创建
        print(f"[DEBUG save_session_resume] 会话不存在，无法保存")
        return

    if lang == 'zh':
        conv.zh_resume = resume_data
        print(f"[DEBUG save_session_resume] 已保存到 zh_resume")
    else:
        conv.en_resume = resume_data
        print(f"[DEBUG save_session_resume] 已保存到 en_resume")
    db.commit()
    print(f"[DEBUG save_session_resume] 提交完成")


def get_session_jd(db, user_id: int, session_id: str) -> dict:
    """获取指定session的JD数据"""
    conv = db.query(Conversation).filter(
        Conversation.user_id == user_id,
        Conversation.session_id == session_id
    ).first()
    if not conv:
        return {}
    return conv.jd_data if conv.jd_data else {}


def save_session_jd(db, user_id: int, session_id: str, jd_data: dict):
    """保存指定session的JD数据"""
    conv = db.query(Conversation).filter(
        Conversation.user_id == user_id,
        Conversation.session_id == session_id
    ).first()
    if not conv:
        return
    conv.jd_data = jd_data
    db.commit()


def ensure_session_exists(db, user_id: int, session_id: str) -> Conversation:
    """确保会话存在，如果不存在则创建"""
    conv = db.query(Conversation).filter(
        Conversation.user_id == user_id,
        Conversation.session_id == session_id
    ).first()

    if not conv:
        conv = Conversation(
            user_id=user_id,
            session_id=session_id,
            title="新会话",
            messages=[],
            compressed_context=[],
            zh_resume={},
            en_resume={},
            jd_data={},
            photo=""
        )
        db.add(conv)
        db.commit()
        db.refresh(conv)

    return conv


def _normalize_session_title(title: str) -> str:
    """规范化会话标题并做长度校验"""
    normalized = (title or "").strip()
    if not normalized:
        raise ValueError("会话标题不能为空")
    if len(normalized) > 50:
        raise ValueError("会话标题不能超过50个字符")
    return normalized


def _extract_summary_text(text: str) -> str:
    """提取用于默认会话命名的摘要文本"""
    content = (text or "").strip()
    if not content or content.startswith("[CONFIRM_REPLY:"):
        return ""
    return content[:20]


def _session_to_dict(conv: Conversation) -> dict:
    """统一会话列表返回结构"""
    return {
        "session_id": conv.session_id,
        "title": conv.title or "新会话",
        "created_at": conv.created_at.isoformat() if conv.created_at else None,
        "last_accessed": conv.last_accessed.isoformat() if conv.last_accessed else None,
        "message_count": len(conv.messages) if isinstance(conv.messages, list) else 0,
        "has_pending_confirmation": bool(conv.pending_confirmation)
    }


def list_user_sessions(db, user_id: int) -> list:
    """获取用户会话列表，按最近访问时间倒序"""
    sessions = db.query(Conversation).filter(
        Conversation.user_id == user_id
    ).order_by(Conversation.last_accessed.desc(), Conversation.created_at.desc()).all()
    return [_session_to_dict(conv) for conv in sessions]


def create_session(db, user_id: int, title: str = "新会话", session_id: str = None) -> dict:
    """创建会话并返回会话信息"""
    normalized_title = _normalize_session_title(title)
    new_session_id = session_id or str(uuid.uuid4())
    conv = Conversation(
        user_id=user_id,
        session_id=new_session_id,
        title=normalized_title,
        messages=[],
        compressed_context=[],
        zh_resume={},
        en_resume={},
        jd_data={},
        photo=""
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return _session_to_dict(conv)


def rename_session(db, user_id: int, session_id: str, title: str) -> dict:
    """重命名会话"""
    conv = db.query(Conversation).filter(
        Conversation.user_id == user_id,
        Conversation.session_id == session_id
    ).first()
    if not conv:
        return None

    conv.title = _normalize_session_title(title)
    db.commit()
    db.refresh(conv)
    return _session_to_dict(conv)


def delete_session(db, user_id: int, session_id: str) -> bool:
    """硬删除会话"""
    conv = db.query(Conversation).filter(
        Conversation.user_id == user_id,
        Conversation.session_id == session_id
    ).first()
    if not conv:
        return False
    db.delete(conv)
    db.commit()
    return True


def update_session_title_if_default(db, user_id: int, session_id: str, first_user_text: str):
    """仅默认标题时，根据首条用户输入自动命名"""
    conv = db.query(Conversation).filter(
        Conversation.user_id == user_id,
        Conversation.session_id == session_id
    ).first()
    if not conv:
        return

    if (conv.title or "").strip() != "新会话":
        return

    summary = _extract_summary_text(first_user_text)
    if not summary:
        return

    conv.title = summary
    db.commit()


def get_session_photo(db, user_id: int, session_id: str) -> str:
    """获取会话的照片"""
    conv = db.query(Conversation).filter(
        Conversation.user_id == user_id,
        Conversation.session_id == session_id
    ).first()
    if not conv:
        return ""

    if conv.photo:
        return conv.photo

    # 兼容旧数据：会话级没有照片时，从旧的 Resume 表懒迁移
    old_resume = db.query(Resume).filter(Resume.user_id == user_id).first()
    if old_resume and old_resume.photo:
        conv.photo = old_resume.photo
        db.commit()
        return conv.photo

    return ""


def save_session_photo(db, user_id: int, session_id: str, photo: str):
    """保存会话的照片"""
    conv = db.query(Conversation).filter(
        Conversation.user_id == user_id,
        Conversation.session_id == session_id
    ).first()
    if conv:
        conv.photo = photo
        db.commit()

    return conv


def update_session_last_accessed(db, user_id: int, session_id: str):
    """更新会话的最后访问时间"""
    conv = db.query(Conversation).filter(
        Conversation.user_id == user_id,
        Conversation.session_id == session_id
    ).first()
    if conv:
        conv.last_accessed = datetime.utcnow()
        db.commit()
