using Microsoft.AspNetCore.Identity;
using System.Security.Claims;
using Microsoft.IdentityModel.Tokens;
using System.Text;
using System.IdentityModel.Tokens.Jwt;
using Patient_Management_System.Data;
using Patient_Management_System.Models;
using Microsoft.EntityFrameworkCore;
using Patient_Management_System.Exceptions;

namespace Patient_Management_System.Services
{
    public class AuthService(AppDbContext context, IConfiguration config)
    {
        private readonly AppDbContext _context = context;
        private readonly IConfiguration _config = config;

        private string GenerateJwtToken(string role, string id)
        {
            var jwtSettings = _config.GetSection("Jwt");
            var claims = new[]
            {
                new Claim(ClaimTypes.Role, role),
                new Claim(ClaimTypes.NameIdentifier, id)
            };
            var key = new SymmetricSecurityKey(Encoding.UTF8.GetBytes(jwtSettings["Key"]));
            var creds = new SigningCredentials(key, SecurityAlgorithms.HmacSha256);

            var token = new JwtSecurityToken(
                issuer: jwtSettings["Issuer"],
                audience: jwtSettings["Audience"],
                claims: claims,
                expires: DateTime.Now.AddHours(1),
                signingCredentials: creds);

            return new JwtSecurityTokenHandler().WriteToken(token);
        }

        public async Task Signup(User user)
        {
            if(user == null || string.IsNullOrWhiteSpace(user.Email) || string.IsNullOrWhiteSpace(user.Password))
            {
                throw new ArgumentException("Invalid user details !!!");
            }
            var userByEmail = await _context.Users.FirstOrDefaultAsync(u => u.Email.ToLower() == user.Email.ToLower());
            if(userByEmail != null)
            {
                throw new DuplicateEmailException(user.Email);
            }

            var passwordHasher = new PasswordHasher<User>();
            user.Password = passwordHasher.HashPassword(user, user.Password);

            User addUser = new()
            {
                Email = user.Email,
                Password = user.Password,
                Role = Enum.Parse<UserRole>(UserRole.USER.ToString()),
            };

            _context.Users.Add(addUser);
            _context.SaveChanges();
        }

        public async Task<string> Login(User user)
        {
            if(user == null || string.IsNullOrWhiteSpace(user.Email) || string.IsNullOrWhiteSpace(user.Password))
            {
                throw new ArgumentException("Invalid user details!!!");
            }

            var userByEmail = await _context.Users.FirstOrDefaultAsync(u => u.Email.ToLower() == user.Email.ToLower()) ?? throw new UnauthorizedAccessException("Invalid User Email!!!");
            
            var passwordHasher = new PasswordHasher<User>();
            var result = passwordHasher.VerifyHashedPassword(userByEmail, userByEmail.Password, user.Password);

            if (result == PasswordVerificationResult.Failed)
            {
                throw new UnauthorizedAccessException("Invalid User Password!!!");
            }

            var token = GenerateJwtToken(userByEmail.Role.ToString(), userByEmail.Id.ToString());
            return token;
        }
    }
}