import jwt
from fastapi import Header, HTTPException, Request

def get_current_user(role_required: str):
    async def _verify_role(request: Request, authorization: str = Header(None)):
        if not authorization:
            token = request.query_params.get("token") or request.query_params.get("jwt")
            if not token:
                raise HTTPException(status_code=401, detail="Missing authorization header or token query param")
            authorization = f"Bearer {token}"
        
        try:
            scheme, token = authorization.split()
            if scheme.lower() != "bearer":
                raise ValueError("Invalid scheme")
        except ValueError:
            raise HTTPException(status_code=401, detail="Invalid authorization header format")
        
        try:
            # We don't verify signature here as Kong Gateway has already verified it.
            # We just decode it to extract the claims.
            payload = jwt.decode(token, options={"verify_signature": False})
            
            user_role = payload.get("role")
            if user_role != role_required:
                raise HTTPException(status_code=403, detail=f"Forbidden. Required role: {role_required}")
            
            request.state.user = payload
            return payload
            
        except jwt.DecodeError:
            raise HTTPException(status_code=401, detail="Invalid token")

    return _verify_role
