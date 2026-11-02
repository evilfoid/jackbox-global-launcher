use std::{
    borrow::Cow,
    fmt::Display,
    ops::{BitOr, BitOrAssign},
    str::FromStr,
};

use serde::{de::Error, Deserialize, Serialize};

/// Permission flags for an ACL entry. Mirrors the subset of `tokio::io::Interest`
/// this crate used, since `Interest::PRIORITY` only exists on Linux.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Interest(u8);

impl Interest {
    pub const READABLE: Self = Self(0b001);
    pub const WRITABLE: Self = Self(0b010);
    pub const PRIORITY: Self = Self(0b100);

    pub fn is_readable(self) -> bool {
        self.0 & Self::READABLE.0 != 0
    }

    pub fn is_writable(self) -> bool {
        self.0 & Self::WRITABLE.0 != 0
    }

    pub fn is_priority(self) -> bool {
        self.0 & Self::PRIORITY.0 != 0
    }
}

impl BitOr for Interest {
    type Output = Self;

    fn bitor(self, rhs: Self) -> Self {
        Self(self.0 | rhs.0)
    }
}

impl BitOrAssign for Interest {
    fn bitor_assign(&mut self, rhs: Self) {
        self.0 |= rhs.0;
    }
}

#[derive(Deserialize, Serialize, Debug, Clone, Copy, PartialEq, Eq, Default)]
#[serde(rename_all = "lowercase")]
pub enum Role {
    Host,
    #[default]
    Player,
    Audience,
    Moderator,
}

impl Display for Role {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Host => write!(f, "host"),
            Self::Player => write!(f, "player"),
            Self::Audience => write!(f, "audience"),
            Self::Moderator => write!(f, "moderator"),
        }
    }
}

impl FromStr for Role {
    type Err = ();

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "host" => Ok(Self::Host),
            "player" => Ok(Self::Player),
            "audience" => Ok(Self::Audience),
            "moderator" => Ok(Self::Moderator),
            _ => Err(()),
        }
    }
}

#[derive(Debug, Clone, Copy)]
pub struct Acl {
    pub interest: Interest,
    pub principle: Principle,
}

impl Acl {
    pub fn default_vec() -> Vec<Self> {
        vec![Self::default()]
    }
}

impl Default for Acl {
    fn default() -> Self {
        Acl {
            interest: Interest::READABLE,
            principle: Principle::Wild,
        }
    }
}

impl Display for Acl {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        if self.interest.is_priority() {
            write!(f, "s")?;
        }
        if self.interest.is_readable() {
            write!(f, "r")?;
        }
        if self.interest.is_writable() {
            write!(f, "w")?;
        }

        write!(f, " {}", self.principle)
    }
}

impl Serialize for Acl {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        format!("{}", self).serialize(serializer)
    }
}

impl<'de> Deserialize<'de> for Acl {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        let acl: Cow<'de, str> = Deserialize::deserialize(deserializer)?;
        Acl::from_str(acl.as_ref()).map_err(|_| {
            D::Error::invalid_value(
                serde::de::Unexpected::Str(acl.as_ref()),
                &"A valid ACL principle",
            )
        })
    }
}

impl FromStr for Acl {
    type Err = ();

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        let split = s.split_once(' ').ok_or(())?;

        let interest = split
            .0
            .chars()
            .try_fold(None, |state, interest| match interest {
                's' => Ok(Some(
                    state.unwrap_or(Interest::PRIORITY) | Interest::PRIORITY,
                )),
                'r' => Ok(Some(
                    state.unwrap_or(Interest::READABLE) | Interest::READABLE,
                )),
                'w' => Ok(Some(
                    state.unwrap_or(Interest::WRITABLE) | Interest::WRITABLE,
                )),
                _ => return Err(()),
            })?
            .ok_or(())?;

        if split.1 == "*" {
            return Ok(Self {
                interest,
                principle: Principle::Wild,
            });
        }

        let split = split.1.split_once(':').ok_or(())?;

        let principle = match split.0 {
            "role" => Principle::Role(split.1.parse()?),
            "id" => Principle::Id(split.1.parse().or(Err(()))?),
            _ => return Err(()),
        };

        Ok(Self {
            interest,
            principle,
        })
    }
}

#[derive(Debug, Clone, Copy)]
pub enum Principle {
    Role(Role),
    Id(i64),
    Wild,
}

impl Principle {
    pub fn matches(&self, role: Role, id: i64) -> bool {
        match *self {
            Self::Role(r) => role == r,
            Self::Id(i) => id == i,
            Self::Wild => true,
        }
    }
}

impl Display for Principle {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Role(r) => write!(f, "role:{}", r),
            Self::Id(id) => write!(f, "id:{}", id),
            Self::Wild => write!(f, "*"),
        }
    }
}
